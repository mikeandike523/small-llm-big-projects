"""Heartbeat runner: launches a heartbeat's instructions as a new-task turn.

The daemon (``heartbeat_daemon.py``) decides *when* a session is due; this
module decides *how* to fire it. Each fire runs on its own thread so a busy
session's cancel-and-retry waits never delay other sessions' heartbeats.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Callable

from src.ui_connector.heartbeat_daemon import HeartbeatSession

logger = logging.getLogger(__name__)

HEARTBEAT_RETRY_SECONDS = 60.0
HEARTBEAT_MAX_CANCEL_ATTEMPTS = 3
HEARTBEAT_FOLLOWUP_BEHAVIOR = "new-task"


def _launch_new_task(session_id: str, text: str) -> bool:
    """Start a turn exactly like clicking Send with "force new task" selected."""
    from src.ui_connector.socket_handler_components.socket_events_turn import (
        new_user_message,
    )

    return new_user_message(
        session_id,
        {"text": text},
        str(uuid.uuid4()),
        HEARTBEAT_FOLLOWUP_BEHAVIOR,
        background=True,
    )


def _cancel_turn(session_id: str) -> None:
    from src.ui_connector.socket_handler_components.socket_events import (
        cancel_session_turn,
    )

    cancel_session_turn(session_id)


class HeartbeatRunner:
    def __init__(
        self,
        *,
        launch: Callable[[str, str], bool] = _launch_new_task,
        cancel: Callable[[str], None] = _cancel_turn,
        retry_seconds: float = HEARTBEAT_RETRY_SECONDS,
        max_cancel_attempts: int = HEARTBEAT_MAX_CANCEL_ATTEMPTS,
    ) -> None:
        self._launch = launch
        self._cancel = cancel
        self._retry_seconds = retry_seconds
        self._max_cancel_attempts = max_cancel_attempts
        self._shutdown = threading.Event()
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()

    def shutdown(self) -> None:
        """Abort any pending cancel-and-retry waits."""
        self._shutdown.set()

    def __call__(self, session: HeartbeatSession) -> None:
        """Daemon callback: validate, then fire on a background thread."""
        session_id = session.session_id
        text = session.instructions.strip()
        if not text:
            logger.warning(
                "Heartbeat invalid: session_id=%s has empty instructions; skipping",
                session_id,
            )
            return
        with self._in_flight_lock:
            if session_id in self._in_flight:
                logger.info(
                    "Heartbeat already in progress: session_id=%s; skipping",
                    session_id,
                )
                return
            self._in_flight.add(session_id)
        try:
            threading.Thread(
                target=self._fire_and_release,
                args=(session_id, text),
                name=f"heartbeat-{session_id}",
                daemon=True,
            ).start()
        except BaseException:
            self._release(session_id)
            raise

    def _release(self, session_id: str) -> None:
        with self._in_flight_lock:
            self._in_flight.discard(session_id)

    def _fire_and_release(self, session_id: str, text: str) -> None:
        try:
            self.fire(session_id, text)
        except Exception:
            logger.exception("Heartbeat run failed: session_id=%s", session_id)
        finally:
            self._release(session_id)

    def fire(self, session_id: str, text: str) -> bool:
        """Launch ``text`` as a new task, cancelling a busy turn first.

        Returns True once the turn is launched. Launching is also the busy
        check: admission is atomic, so a turn the user starts between a check
        and a launch can never be clobbered.
        """
        attempt = 0
        while True:
            if self._launch(session_id, text):
                logger.info("Heartbeat launched: session_id=%s (new task)", session_id)
                return True
            if attempt >= self._max_cancel_attempts:
                break
            attempt += 1
            logger.warning(
                "Heartbeat blocked: session_id=%s is busy; sending cancel "
                "(attempt %d/%d) and retrying in %.0f seconds",
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
        logger.error(
            "Heartbeat failed: session_id=%s is still busy after %d cancel "
            "attempts; the session appears orphaned. Restarting the SLBP server "
            "is recommended.",
            session_id,
            self._max_cancel_attempts,
        )
        return False
