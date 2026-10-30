"""Low-overhead Gmail watch renewal and history-sync scheduling."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from src.channels.email.config import EmailConfig
from src.channels.email.notification_store import pending_notification_count
from src.channels.email.state import GmailMailboxState, load_mailbox_state
from src.channels.email.sync import synchronize_mailbox
from src.channels.email.watch import register_or_renew_watch

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 5 * 60
RENEWAL_INTERVAL_SECONDS = 24 * 60 * 60


def is_watch_refresh_due(
    state: GmailMailboxState,
    now_unix: float,
    renewal_interval_seconds: float = RENEWAL_INTERVAL_SECONDS,
) -> bool:
    if state.watch_next_attempt_unix is not None:
        return now_unix >= state.watch_next_attempt_unix
    return (
        state.watch_last_success_unix is None
        or now_unix - state.watch_last_success_unix >= renewal_interval_seconds
    )


class EmailWatchDaemon:
    """Run one immediate audit, then sleep efficiently until work or timeout."""

    def __init__(
        self,
        *,
        config: EmailConfig,
        gmail_factory: Callable[[], Any],
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._gmail_factory = gmail_factory
        self._interval_seconds = interval_seconds
        self._wall_time = wall_time
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._startup_sync_pending = True

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="email-watch-daemon",
                daemon=True,
            )
            self._thread.start()

    def notify(self) -> None:
        """Wake promptly after a durable Pub/Sub notification is committed."""
        self._wake_event.set()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
            self._wake_event.set()
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning(
                "Email watch daemon did not stop within %.1f seconds", timeout
            )
        else:
            logger.info("Email watch daemon stopped")

    def run_cycle(self) -> None:
        now = self._wall_time()
        state = load_mailbox_state(self._config.mailbox_email)
        gmail: Any | None = None
        if is_watch_refresh_due(state, now):
            try:
                gmail = self._gmail_factory()
                register_or_renew_watch(gmail, self._config, now=now)
            except Exception:
                logger.exception(
                    "Gmail watch renewal failed; continuing with any pending sync"
                )
            state = load_mailbox_state(self._config.mailbox_email)

        has_notifications = pending_notification_count(self._config.mailbox_email) > 0
        if state.last_processed_history_id and (
            has_notifications or self._startup_sync_pending
        ):
            gmail = gmail or self._gmail_factory()
            synchronized = synchronize_mailbox(gmail, self._config, now=now)
            if synchronized:
                self._startup_sync_pending = False

    def _loop(self) -> None:
        logger.info(
            "Email watch daemon started: mailbox=%s check_interval_seconds=%s",
            self._config.mailbox_email,
            self._interval_seconds,
        )
        while not self._stop_event.is_set():
            self._wake_event.clear()
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Email watch daemon cycle failed")
            self._wake_event.wait(self._interval_seconds)
