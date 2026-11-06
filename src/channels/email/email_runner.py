"""Runs queued emails as email-origin turns and sends every reply.

One daemon thread does all of it, so replies about one email are always sent
in order (queued -> working -> final). It wakes when mail is queued, when any
turn reservation is released, when a turn starts waiting for approval, when
settings change, and every ``SWEEP_SECONDS`` as a fallback. A pass first gives
new mail to its conversation's session, spawning the session on a conversation's
first email. Then, per session with pending work, it:

1. sends each owed end-of-turn reply (answer / error / cancellation);
2. sends each owed awaiting-approval notice;
3. sends each owed ``[message queued]`` note;
4. unless an email turn it launched is still running, claims the oldest
   queued email (compare-and-set) and launches it; busy -> back to queued.

Sessions do not wait for each other, so conversations run in parallel while each
one stays in order.

Turn threads only record outcomes in the database (``on_finished``) and wake
the runner; they never send mail themselves. A failed end-of-turn, approval or
queued reply leaves its column empty, so a later pass retries it. The
``[... is working...]`` note is only tried once: sent late, it would be
misleading.

The queued and working notes are progress notes, sent only when
``system.channels.email.system-messages.enabled`` is true. End-of-turn replies
and the awaiting-approval notice are always sent: the first is the sender's only
answer, and the second explains why that answer has stopped coming.
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
from src.channels.email.session_spawn import ensure_user_folder, session_for_email
from src.utils.agent_store import agent_for_session
from src.utils.automation_approval_policies import AUTOMATION_FOLLOWUP_FORCE_FOLLOW_UP
from src.utils.param_helper import get_param_value
from src.utils.sql.agents_db import Agent
from src.utils.sql.kv_manager import KVManager

logger = logging.getLogger(__name__)

SWEEP_SECONDS = 30.0
INTERRUPTED_NOTE = (
    "[Turn interrupted. You can re-send your message by replying to this email.]"
)
SYSTEM_MESSAGES_PARAM = "system.channels.email.system-messages.enabled"
ADMIN_NAME_PARAM = "system.metadata.system-admin.contact-name"
ADMIN_EMAIL_PARAM = "system.metadata.system-admin.contact-email"

Launch = Callable[[str, str, str, Callable[[Any], None]], bool]


def _read_global_param(name: str) -> Any:
    from src.data import get_pool

    with get_pool().get_connection() as conn:
        return get_param_value(KVManager(conn), name)


def _launch_email_turn(session_id: str, text: str, title: str, on_finished) -> bool:
    from src.ui_connector.socket_handler_components.socket_events_turn import (
        new_user_message,
    )
    from src.utils.session_model import SUBTURN_ORIGIN_EMAIL

    # A session is one conversation: its first email has no earlier turn, so this
    # starts a new task, and every reply continues it.
    return new_user_message(
        session_id,
        {"text": text},
        str(uuid.uuid4()),
        AUTOMATION_FOLLOWUP_FORCE_FOLLOW_UP,
        background=True,
        origin=SUBTURN_ORIGIN_EMAIL,
        on_finished=on_finished,
        fixed_title=title,
    )


def turn_title(row: InboundEmail) -> str:
    return f"Message from {row.sender_address}, id={row.gmail_thread_id}"


def agent_label(agent: Agent | None) -> str:
    """The agent's name for status replies; falls back to a generic label."""
    return (agent.name if agent is not None else None) or "The agent"


def queued_note(_agent: str) -> str:
    return "[message queued]"


def working_note(agent: str) -> str:
    return f"[{agent} is working...]"


def _admin_contact(admin_name: str | None, admin_email: str | None) -> str:
    name = (admin_name or "").strip()
    address = (admin_email or "").strip()
    if name and address:
        return f"system administrator {name} at mailto:{address}"
    if name:
        return f"system administrator {name}"
    if address:
        return f"your system administrator at mailto:{address}"
    return "your system administrator"


def failed_note(agent: str, admin_name: str | None, admin_email: str | None) -> str:
    """The error text is for operators: it stays in ``error_detail`` and the UI."""
    contact = _admin_contact(admin_name, admin_email)
    return f"[{agent} had a network or system error. Please contact {contact}]"


def cancelled_note(agent: str) -> str:
    return f"[{agent}'s task was cancelled in session UI]"


def approval_note(agent: str, admin_name: str | None, admin_email: str | None) -> str:
    contact = _admin_contact(admin_name, admin_email)
    return (
        f"[{agent} is awaiting approval on the system UI. If you were not expecting "
        f"this message, please contact {contact}]"
    )


class EmailRunner:
    def __init__(
        self,
        *,
        config: EmailConfig,
        gmail_factory: Callable[[], Any],
        launch: Launch = _launch_email_turn,
        agent_for: Callable[[str], Agent | None] = agent_for_session,
        assign_session: Callable[[InboundEmail], str] = session_for_email,
        ensure_folder: Callable[[InboundEmail], None] = ensure_user_folder,
        read_param: Callable[[str], Any] = _read_global_param,
        sweep_seconds: float = SWEEP_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._gmail_factory = gmail_factory
        self._gmail: Any | None = None
        self._launch = launch
        self._agent_for = agent_for
        self._assign_session = assign_session
        self._ensure_folder = ensure_folder
        self._read_param = read_param
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
        self._assign_new_mail()
        for session_id in store.sessions_with_pending_work():
            try:
                self._process_session(session_id)
            except Exception:
                logger.exception("Email runner failed for session_id=%s", session_id)

    def _assign_new_mail(self) -> None:
        for row in store.queued_without_session():
            try:
                store.assign_session(row.id, self._assign_session(row))
            except Exception:
                # It stays queued, so a later pass tries again.
                logger.exception("Email session spawn failed: inbound_id=%s", row.id)

    def _process_session(self, session_id: str) -> None:
        agent = self._agent_for(session_id)
        label = agent_label(agent)
        # Read each pass, so changing the param needs no restart.
        progress_notes = bool(self._read_param(SYSTEM_MESSAGES_PARAM))
        for row in store.finished_needing_final_reply(session_id):
            self._send_final(row, agent, label)
        for row in store.running_needing_approval_notice(session_id):
            self._send_status(
                row,
                store.REPLY_APPROVAL,
                approval_note(
                    label,
                    self._read_param(ADMIN_NAME_PARAM),
                    self._read_param(ADMIN_EMAIL_PARAM),
                ),
            )
        if progress_notes:
            for row in store.queued_needing_queued_reply(session_id):
                self._send_status(row, store.REPLY_QUEUED, queued_note(label))
        with self._running_lock:
            if session_id in self._running:
                return
        row = store.oldest_queued(session_id)
        if row is None or not store.try_mark_running(row.id):
            return
        self._start_turn(session_id, row, label, progress_notes)

    def _start_turn(
        self, session_id: str, row: InboundEmail, label: str, progress_notes: bool
    ) -> None:
        with self._running_lock:
            self._running.add(session_id)
        try:
            self._ensure_folder(row)
            launched = self._launch(
                session_id,
                frame_inbound_email(row),
                turn_title(row),
                lambda outcome: self._on_finished(session_id, row, outcome),
            )
        except Exception:
            logger.exception("Email turn launch failed: session_id=%s", session_id)
            launched = False
        if not launched:
            with self._running_lock:
                self._running.discard(session_id)
            store.requeue(row.id)
            # Busy (e.g. a human's turn started first): tell the sender once.
            if progress_notes and row.queued_reply_sent_at is None:
                self._send_status(row, store.REPLY_QUEUED, queued_note(label))
            return
        logger.info(
            "Email turn launched: session_id=%s inbound_id=%s sender=%s",
            session_id,
            row.id,
            row.sender_address,
        )
        if progress_notes:
            self._send_status(row, store.REPLY_WORKING, working_note(label))

    def _on_finished(self, session_id: str, row: InboundEmail, outcome: Any) -> None:
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
                self._running.discard(session_id)
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

    def _send_final(self, row: InboundEmail, agent: Agent | None, label: str) -> bool:
        if row.status == store.STATUS_DONE:
            agent_name = (agent.name if agent is not None else None) or ""
            return self._send(
                row,
                store.REPLY_FINAL,
                lambda: build_final_reply(row, agent_name, row.final_text or ""),
            )
        if row.status == store.STATUS_CANCELLED:
            text = cancelled_note(label)
        elif row.status == store.STATUS_INTERRUPTED:
            text = INTERRUPTED_NOTE
        else:
            text = failed_note(
                label,
                self._read_param(ADMIN_NAME_PARAM),
                self._read_param(ADMIN_EMAIL_PARAM),
            )
        return self._send_status(row, store.REPLY_FINAL, text)


_runner_lock = threading.Lock()
_runner: EmailRunner | None = None


def start_email_runner(config: EmailConfig, gmail_factory: Callable[[], Any]) -> None:
    global _runner
    from src.ui_connector.socket_handler_components.state import (
        add_approval_wait_listener,
        add_turn_release_listener,
    )

    with _runner_lock:
        if _runner is None:
            _runner = EmailRunner(config=config, gmail_factory=gmail_factory)
        runner = _runner
    add_turn_release_listener(_on_turn_released)
    add_approval_wait_listener(on_approval_wait)
    runner.start()


def stop_email_runner() -> None:
    global _runner
    with _runner_lock:
        runner, _runner = _runner, None
    if runner is not None:
        runner.stop()


def _on_turn_released(_session_id: str) -> None:
    notify_email_runner()


def on_approval_wait(session_id: str) -> None:
    """Runs on the turn thread: record only, then wake the runner to send it."""
    from src.ui_connector.socket_handler_components.state import reserved_turn_origin
    from src.utils.session_model import SUBTURN_ORIGIN_EMAIL

    # A person at the UI already knows; only an email sender is left wondering.
    if reserved_turn_origin(session_id) != SUBTURN_ORIGIN_EMAIL:
        return
    if store.request_approval_notice(session_id, time.time()):
        notify_email_runner()


def notify_email_runner() -> None:
    with _runner_lock:
        runner = _runner
    if runner is not None:
        runner.notify()
