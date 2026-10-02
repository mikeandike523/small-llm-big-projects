"""Heartbeat runner: sends a heartbeat's instructions as a message.

The message is admitted with the session's configured follow-up behavior
(heartbeat settings `followup_behavior`: "auto", "follow-up" or "new-task"),
like Send with the chat footer's matching option. With "auto" the continuation
watchdog decides. A continuation appends a heartbeat-origin subturn, so the
turn's owner (its latest subturn's origin) flips to heartbeat.

The daemon (``heartbeat_daemon.py``) decides *when* a session is due; this
module decides *how* to fire it:

* idle session -> launch now;
* a user owns the running turn -> skip without cancelling anything; the last
  run stays unrecorded so the daemon's next cycle reconsiders the session;
* a heartbeat owns the running turn (a stuck earlier heartbeat) -> cancel it
  and retry on a background thread, so the waits never delay other sessions.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Callable

from src.ui_connector.heartbeat_daemon import HeartbeatSession
from src.utils.session_model import SUBTURN_ORIGIN_HEARTBEAT, SUBTURN_ORIGIN_USER

logger = logging.getLogger(__name__)

HEARTBEAT_RETRY_SECONDS = 60.0
HEARTBEAT_MAX_CANCEL_ATTEMPTS = 3


def _launch_heartbeat(session_id: str, text: str, followup_behavior: str) -> bool:
    """Send a message exactly like clicking Send with that follow-up option."""
    from src.ui_connector.socket_handler_components.socket_events_turn import (
        new_user_message,
    )

    return new_user_message(
        session_id,
        {"text": text},
        str(uuid.uuid4()),
        followup_behavior,
        background=True,
        origin=SUBTURN_ORIGIN_HEARTBEAT,
    )


def _running_turn_owner(session_id: str) -> str | None:
    from src.ui_connector.socket_handler_components.state import (
        reserved_turn_origin,
    )

    return reserved_turn_origin(session_id)


def _cancel_turn(session_id: str) -> None:
    from src.ui_connector.socket_handler_components.socket_events import (
        cancel_session_turn,
    )

    cancel_session_turn(session_id)


_LAUNCHED = "launched"
_USER_OWNED = "user-owned"
_BUSY = "busy"


class HeartbeatRunner:
    def __init__(
        self,
        *,
        launch: Callable[[str, str, str], bool] = _launch_heartbeat,
        running_turn_owner: Callable[[str], str | None] = _running_turn_owner,
        cancel: Callable[[str], None] = _cancel_turn,
        record_run: Callable[[str], None] = lambda _session_id: None,
        retry_seconds: float = HEARTBEAT_RETRY_SECONDS,
        max_cancel_attempts: int = HEARTBEAT_MAX_CANCEL_ATTEMPTS,
    ) -> None:
        self._launch = launch
        self._running_turn_owner = running_turn_owner
        self._cancel = cancel
        self._record_run = record_run
        self._retry_seconds = retry_seconds
        self._max_cancel_attempts = max_cancel_attempts
        self._shutdown = threading.Event()
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()

    def shutdown(self) -> None:
        """Abort any pending cancel-and-retry waits."""
        self._shutdown.set()

    def __call__(self, session: HeartbeatSession) -> bool:
        """Daemon callback. True means "record this run now".

        False means either skipped (reconsider next cycle) or handed to the
        cancel-and-retry thread, which records the run itself when it ends.
        """
        session_id = session.session_id
        text = session.instructions.strip()
        behavior = session.followup_behavior
        if not text:
            logger.warning(
                "Heartbeat invalid: session_id=%s has empty instructions; skipping",
                session_id,
            )
            return False
        with self._in_flight_lock:
            if session_id in self._in_flight:
                logger.info(
                    "Heartbeat already in progress: session_id=%s; skipping",
                    session_id,
                )
                return False
            self._in_flight.add(session_id)

        handed_off = False
        try:
            outcome = self._try_launch(session_id, text, behavior)
            if outcome == _LAUNCHED:
                return True
            if outcome == _USER_OWNED:
                return False
            threading.Thread(
                target=self._retry_and_release,
                args=(session_id, text, behavior),
                name=f"heartbeat-{session_id}",
                daemon=True,
            ).start()
            handed_off = True
            return False
        finally:
            if not handed_off:
                self._release(session_id)

    def _release(self, session_id: str) -> None:
        with self._in_flight_lock:
            self._in_flight.discard(session_id)

    def _try_launch(self, session_id: str, text: str, behavior: str) -> str:
        """One launch attempt. Launching is also the busy check: admission is
        atomic, so a turn a user starts at the same moment is never clobbered.
        """
        for _ in range(2):
            if self._launch(session_id, text, behavior):
                logger.info(
                    "Heartbeat launched: session_id=%s (followup_behavior=%s)",
                    session_id,
                    behavior,
                )
                return _LAUNCHED
            owner = self._running_turn_owner(session_id)
            if owner == SUBTURN_ORIGIN_USER:
                logger.info(
                    "Heartbeat skipped: session_id=%s has a running user turn; "
                    "will reconsider at the next heartbeat cycle",
                    session_id,
                )
                return _USER_OWNED
            if owner is not None:
                return _BUSY
            # The turn ended between the launch and the owner check; retry once.
        return _BUSY

    def _retry_and_release(self, session_id: str, text: str, behavior: str) -> None:
        try:
            self.cancel_and_retry(session_id, text, behavior)
        except Exception:
            logger.exception("Heartbeat run failed: session_id=%s", session_id)
        finally:
            self._release(session_id)

    def cancel_and_retry(self, session_id: str, text: str, behavior: str) -> bool:
        """Cancel a heartbeat-owned turn and retry; True once launched.

        Records the run when launched or declared orphaned. A user taking over
        the session meanwhile ends this without cancelling their turn and
        without recording, so the next cycle reconsiders the session.
        """
        for attempt in range(1, self._max_cancel_attempts + 1):
            logger.warning(
                "Heartbeat blocked: session_id=%s is busy with a heartbeat turn; "
                "sending cancel (attempt %d/%d) and retrying in %.0f seconds",
                session_id,
                attempt,
                self._max_cancel_attempts,
                self._retry_seconds,
            )
            self._cancel(session_id)
            if self._shutdown.wait(self._retry_seconds):
                logger.info(
                    "Heartbeat abandoned during shutdown: session_id=%s", session_id
                )
                return False
            outcome = self._try_launch(session_id, text, behavior)
            if outcome == _LAUNCHED:
                self._record_run(session_id)
                return True
            if outcome == _USER_OWNED:
                return False
        logger.error(
            "Heartbeat failed: session_id=%s is still busy after %d cancel "
            "attempts; the session appears orphaned. Restarting the SLBP server "
            "is recommended.",
            session_id,
            self._max_cancel_attempts,
        )
        self._record_run(session_id)
        return False
