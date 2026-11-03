"""Runs queued emails as email-origin turns and sends every reply.

One daemon thread does all of it, so replies about one email are always sent
in order (queued -> working -> final). It wakes when mail is queued, when any
turn reservation is released, when settings change, and every
``SWEEP_SECONDS`` as a fallback. Per session with pending work, a pass:

1. sends each owed end-of-turn reply (answer / error / cancellation);
2. sends each owed ``[message queued]`` note;
3. unless an email turn it launched is still running, claims the oldest
   queued email (compare-and-set) and launches it; busy -> back to queued.

Turn threads only record outcomes in the database (``on_finished``) and wake
the runner; they never send mail themselves. A failed end-of-turn or queued
reply leaves its ``*_reply_sent_at`` column empty, so a later pass retries it.
The ``[... is working...]`` note is only tried once: sent late, it would be
misleading.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from src.channels.email import inbound_store as store
from src.channels.email.config import EmailConfig
from src.channels.email.framing import frame_inbound_email
from src.channels.email.google_errors import log_google_error
from src.channels.email.inbound_store import InboundEmail
from src.channels.email.outbound import (
    build_final_reply,
    build_status_reply,
    send_message,
)
from src.channels.email.router import email_settings_for
from src.utils.email_settings import email_agent_label

logger = logging.getLogger(__name__)

SWEEP_SECONDS = 30.0
INTERRUPTED_NOTE = (
    "[Turn interrupted. You can re-send your message by replying to this email.]"
)

Launch = Callable[[str, str, str, Callable[[Any], None]], bool]


def _launch_email_turn(
    session_id: str, text: str, followup_behavior: str, on_finished
) -> bool:
    from src.ui_connector.socket_handler_components.socket_events_turn import (
        new_user_message,
    )
    from src.utils.session_model import SUBTURN_ORIGIN_EMAIL

    return new_user_message(
        session_id,
        {"text": text},
        str(uuid.uuid4()),
        followup_behavior,
        background=True,
        origin=SUBTURN_ORIGIN_EMAIL,
        on_finished=on_finished,
    )


def queued_note(_agent: str) -> str:
    return "[message queued]"


def working_note(agent: str) -> str:
    return f"[{agent} is working...]"


def failed_note(agent: str, error: str | None) -> str:
    return f"[{agent} could not finish: {error or 'unknown error'}]"


def cancelled_note(agent: str) -> str:
    return f"[{agent}'s task was cancelled in session UI]"


class EmailRunner:
    def __init__(
        self,
        *,
        config: EmailConfig,
        gmail_factory: Callable[[], Any],
        launch: Launch = _launch_email_turn,
        settings_for: Callable[[str], dict] = email_settings_for,
        sweep_seconds: float = SWEEP_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._gmail_factory = gmail_factory
        self._gmail: Any | None = None
        self._launch = launch
        self._settings_for = settings_for
        self._sweep_seconds = sweep_seconds
        self._clock = clock
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running_lock = threading.Lock()
        # Sessions with an email turn this runner launched and not yet finished.
        self._running: set[str] = set()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        interrupted = store.mark_orphaned_interrupted()
        if interrupted:
            logger.warning(
                "Email runner: %d email turn(s) were interrupted by a server "
                "restart; senders will be told",
                interrupted,
            )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"email-runner-{uuid.uuid4()}", daemon=True
        )
        self._thread.start()
        self.notify()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._sweep_seconds)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self.run_pass()
            except Exception:
                logger.exception("Email runner pass failed")

    # -- one pass ----------------------------------------------------------

    def run_pass(self) -> None:
        for session_id in store.sessions_with_pending_work():
            try:
                self._process_session(session_id)
            except Exception:
                logger.exception("Email runner failed for session_id=%s", session_id)

    def _process_session(self, session_id: str) -> None:
        settings = self._settings_for(session_id)
        agent = email_agent_label(settings)
        for row in store.finished_needing_final_reply(session_id):
            self._send_final(row, settings, agent)
        for row in store.queued_needing_queued_reply(session_id):
            self._send_status(row, store.REPLY_QUEUED, queued_note(agent))
        with self._running_lock:
            if session_id in self._running:
                return
        row = store.oldest_queued(session_id)
        if row is None or not store.try_mark_running(row.id):
            return
        self._start_turn(row, settings, agent)

    def _start_turn(self, row: InboundEmail, settings: dict, agent: str) -> None:
        session_id = row.session_id
        with self._running_lock:
            self._running.add(session_id)
        try:
            launched = self._launch(
                session_id,
                frame_inbound_email(row),
                settings["followup_behavior"],
                lambda outcome: self._on_finished(row, outcome),
            )
        except Exception:
            logger.exception("Email turn launch failed: session_id=%s", session_id)
            launched = False
        if not launched:
            with self._running_lock:
                self._running.discard(session_id)
            store.requeue(row.id)
            # Busy (e.g. a human's turn started first): tell the sender once.
            if row.queued_reply_sent_at is None:
                self._send_status(row, store.REPLY_QUEUED, queued_note(agent))
            return
        logger.info(
            "Email turn launched: session_id=%s inbound_id=%s sender=%s",
            session_id,
            row.id,
            row.sender_address,
        )
        self._send_status(row, store.REPLY_WORKING, working_note(agent))

    def _on_finished(self, row: InboundEmail, outcome: Any) -> None:
        """Runs on the turn thread: record only, then wake the runner."""
        try:
            if outcome.cancelled:
                store.mark_finished(row.id, store.STATUS_CANCELLED)
            elif outcome.final_text is not None:
                store.mark_finished(
                    row.id, store.STATUS_DONE, final_text=outcome.final_text
                )
            else:
                store.mark_finished(
                    row.id, store.STATUS_FAILED, error_detail=outcome.error
                )
        finally:
            with self._running_lock:
                self._running.discard(row.session_id)
            self.notify()

    # -- sending -----------------------------------------------------------

    def _client(self) -> Any:
        if self._gmail is None:
            self._gmail = self._gmail_factory()
        return self._gmail

    def _send(self, row: InboundEmail, column: str, build) -> bool:
        try:
            send_message(self._client(), row, build())
        except Exception as exc:
            log_google_error(
                "gmail.users.messages.send",
                exc,
                mailbox=self._config.mailbox_email,
                context={"inbound_id": row.id, "reply": column},
            )
            return False
        store.mark_reply_sent(row.id, column, self._clock())
        return True

    def _send_status(self, row: InboundEmail, column: str, text: str) -> bool:
        return self._send(
            row, column, lambda: build_status_reply(row, self._config, text)
        )

    def _send_final(self, row: InboundEmail, settings: dict, agent: str) -> bool:
        if row.status == store.STATUS_DONE:
            agent_name = str(settings.get("agent_name") or "").strip()
            return self._send(
                row,
                store.REPLY_FINAL,
                lambda: build_final_reply(row, agent_name, row.final_text or ""),
            )
        if row.status == store.STATUS_CANCELLED:
            text = cancelled_note(agent)
        elif row.status == store.STATUS_INTERRUPTED:
            text = INTERRUPTED_NOTE
        else:
            text = failed_note(agent, row.error_detail)
        return self._send_status(row, store.REPLY_FINAL, text)


_runner_lock = threading.Lock()
_runner: EmailRunner | None = None


def start_email_runner(config: EmailConfig, gmail_factory: Callable[[], Any]) -> None:
    global _runner
    from src.ui_connector.socket_handler_components.state import (
        add_turn_release_listener,
    )

    with _runner_lock:
        if _runner is None:
            _runner = EmailRunner(config=config, gmail_factory=gmail_factory)
        runner = _runner
    add_turn_release_listener(_on_turn_released)
    runner.start()


def stop_email_runner() -> None:
    global _runner
    with _runner_lock:
        runner, _runner = _runner, None
    if runner is not None:
        runner.stop()


def _on_turn_released(_session_id: str) -> None:
    notify_email_runner()


def notify_email_runner() -> None:
    with _runner_lock:
        runner = _runner
    if runner is not None:
        runner.notify()


def discard_queued_email(session_id: str) -> int:
    """Drop not-yet-started mail (alias changed or email disabled); no replies."""
    return store.discard_queued(session_id)
