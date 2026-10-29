"""Low-overhead scheduling for Gmail watch renewal checks."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from src.channels.email.watch_state import GmailWatchState

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 5 * 60
RENEWAL_INTERVAL_SECONDS = 24 * 60 * 60


def is_watch_refresh_due(
    last_success_unix: float | None,
    now_unix: float,
    renewal_interval_seconds: float = RENEWAL_INTERVAL_SECONDS,
) -> bool:
    return (
        last_success_unix is None
        or now_unix - last_success_unix >= renewal_interval_seconds
    )


class EmailWatchDaemon:
    """Immediately audit renewal state, then repeat via a non-busy event wait."""

    def __init__(
        self,
        *,
        state_provider: Callable[[], GmailWatchState],
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self._state_provider = state_provider
        self._interval_seconds = interval_seconds
        self._wall_time = wall_time
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._due_logged = False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="email-watch-daemon",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning(
                "Email watch daemon did not stop within %.1f seconds", timeout
            )
        else:
            logger.info("Email watch daemon stopped")

    def run_cycle(self) -> bool:
        state = self._state_provider()
        now = self._wall_time()
        due = is_watch_refresh_due(state.last_success_unix, now)
        if due and not self._due_logged:
            logger.info(
                "Email watch renewal is due: last_success_unix=%s",
                state.last_success_unix,
            )
            self._due_logged = True
        elif not due:
            self._due_logged = False
            logger.debug(
                "Email watch renewal is not due: last_success_unix=%s",
                state.last_success_unix,
            )
        return due

    def _loop(self) -> None:
        logger.info(
            "Email watch daemon started: check_interval_seconds=%s",
            self._interval_seconds,
        )
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Email watch renewal-state check failed")
            if self._stop_event.wait(self._interval_seconds):
                return
