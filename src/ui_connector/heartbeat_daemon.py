"""Low-overhead heartbeat scheduling for persisted sessions."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, Iterable, Protocol

from src.utils.heartbeat_settings import HEARTBEAT_INTERVALS_MINUTES
from src.utils.sql.session_store_db import (
    list_session_meta,
    load_heartbeat_last_runs,
    upsert_heartbeat_last_run,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeartbeatSession:
    session_id: str
    interval_minutes: int
    instructions: str


@dataclass(frozen=True)
class HeartbeatCycleSummary:
    enabled: int
    slated: int
    waiting: int
    first_time: int
    invalid: int


class LastRunStore(Protocol):
    def get(self, session_id: str) -> float | None: ...

    def record(self, session_id: str, unix_time: float) -> None: ...

    def discard(self, session_id: str) -> None: ...


class DurableLastRunMap:
    """Locked, write-through cache of durable heartbeat run timestamps."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._values = load_heartbeat_last_runs()

    def get(self, session_id: str) -> float | None:
        with self._lock:
            return self._values.get(session_id)

    def record(self, session_id: str, unix_time: float) -> None:
        with self._lock:
            upsert_heartbeat_last_run(session_id, unix_time)
            self._values[session_id] = unix_time

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def discard(self, session_id: str) -> None:
        """Forget state after the database row is cascade-deleted."""
        with self._lock:
            self._values.pop(session_id, None)


def _load_enabled_sessions() -> list[HeartbeatSession]:
    from src.ui_connector.socket_handler_components import runtime_settings
    from src.ui_connector.socket_handler_components.session_store import _load_session

    enabled: list[HeartbeatSession] = []
    for row in list_session_meta():
        if not row.get("heartbeat_enabled"):
            continue
        session_id = row["session_id"]
        session = _load_session(session_id)
        settings = runtime_settings.snapshot(session_id, session).heartbeat_settings
        if not settings.get("enabled"):
            continue
        enabled.append(
            HeartbeatSession(
                session_id=session_id,
                interval_minutes=int(settings["interval_minutes"]),
                instructions=str(settings.get("instructions") or ""),
            )
        )
    return enabled


def _run_heartbeat_stub(session: HeartbeatSession) -> None:
    logger.info("Running heartbeat for session %s", session.session_id)


class HeartbeatDaemon:
    def __init__(
        self,
        *,
        sessions_provider: Callable[[], Iterable[HeartbeatSession]],
        run_heartbeat: Callable[[HeartbeatSession], None],
        last_runs: LastRunStore,
        interval_seconds: float,
        wall_time: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions_provider = sessions_provider
        self._run_heartbeat = run_heartbeat
        self._last_runs = last_runs
        self._interval_seconds = interval_seconds
        self._wall_time = wall_time
        self._monotonic = monotonic
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="heartbeat-daemon",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
            self._wake_event.set()
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning("Heartbeat daemon did not stop within %.1f seconds", timeout)
        else:
            logger.info("Heartbeat daemon stopped")

    def settings_changed(self, session_id: str) -> None:
        logger.info("Heartbeat settings changed: session_id=%s", session_id)
        self._wake_event.set()

    def session_deleted(self, session_id: str) -> None:
        self._last_runs.discard(session_id)

    def run_cycle(self) -> HeartbeatCycleSummary:
        now = self._wall_time()
        sessions = list(self._sessions_provider())
        due: list[HeartbeatSession] = []
        waiting = 0
        first_time = 0
        invalid = 0

        for session in sessions:
            if not session.instructions.strip():
                invalid += 1
                continue
            last_run = self._last_runs.get(session.session_id)
            if last_run is None:
                first_time += 1
                due.append(session)
            elif now - last_run >= session.interval_minutes * 60:
                due.append(session)
            else:
                waiting += 1

        summary = HeartbeatCycleSummary(
            enabled=len(sessions),
            slated=len(due),
            waiting=waiting,
            first_time=first_time,
            invalid=invalid,
        )
        logger.info(
            "Heartbeat cycle: enabled=%d slated=%d waiting=%d first_time=%d invalid=%d",
            summary.enabled,
            summary.slated,
            summary.waiting,
            summary.first_time,
            summary.invalid,
        )

        for session in due:
            try:
                self._run_heartbeat(session)
                self._last_runs.record(session.session_id, now)
            except Exception:
                logger.exception(
                    "Heartbeat run failed: session_id=%s", session.session_id
                )
        return summary

    def _loop(self) -> None:
        logger.info(
            "Heartbeat daemon started: interval_minutes=%s",
            self._interval_seconds / 60,
        )
        next_run = self._monotonic() + self._interval_seconds
        while not self._stop_event.is_set():
            timeout = max(0.0, next_run - self._monotonic())
            woke_early = self._wake_event.wait(timeout=timeout)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            if woke_early:
                logger.info("Heartbeat daemon rescheduling after settings change")
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Heartbeat cycle failed")
            next_run = self._monotonic() + self._interval_seconds


_daemon_lock = threading.Lock()
_daemon: HeartbeatDaemon | None = None


def start_heartbeat_daemon() -> HeartbeatDaemon:
    """Start the process-wide daemon once and return it."""
    global _daemon
    with _daemon_lock:
        if _daemon is None:
            minimum_minutes = min(HEARTBEAT_INTERVALS_MINUTES)
            _daemon = HeartbeatDaemon(
                sessions_provider=_load_enabled_sessions,
                run_heartbeat=_run_heartbeat_stub,
                last_runs=DurableLastRunMap(),
                interval_seconds=minimum_minutes * 60,
            )
        _daemon.start()
        return _daemon


def stop_heartbeat_daemon() -> None:
    with _daemon_lock:
        daemon = _daemon
    if daemon is not None:
        daemon.stop()


def notify_heartbeat_settings_changed(session_id: str) -> None:
    with _daemon_lock:
        daemon = _daemon
    if daemon is not None:
        daemon.settings_changed(session_id)


def forget_heartbeat_session(session_id: str) -> None:
    with _daemon_lock:
        daemon = _daemon
    if daemon is not None:
        daemon.session_deleted(session_id)
