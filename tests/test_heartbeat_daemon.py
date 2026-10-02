from __future__ import annotations

import logging
import threading

import src.ui_connector.heartbeat_daemon as heartbeat_daemon
from src.ui_connector.heartbeat_daemon import (
    DurableLastRunMap,
    HeartbeatDaemon,
    HeartbeatSession,
)


class MemoryLastRuns:
    def __init__(self, values: dict[str, float] | None = None) -> None:
        self.values = dict(values or {})
        self.lock = threading.Lock()

    def get(self, session_id: str) -> float | None:
        with self.lock:
            return self.values.get(session_id)

    def record(self, session_id: str, unix_time: float) -> None:
        with self.lock:
            self.values[session_id] = unix_time

    def discard(self, session_id: str) -> None:
        with self.lock:
            self.values.pop(session_id, None)


def test_cycle_counts_and_records_successful_runs(caplog) -> None:
    now = 10_000.0
    sessions = [
        HeartbeatSession("first", 5, "do work", "auto"),
        HeartbeatSession("due", 5, "do work", "auto"),
        HeartbeatSession("waiting", 30, "do work", "auto"),
        HeartbeatSession("invalid", 5, "  \t", "auto"),
    ]
    last_runs = MemoryLastRuns({"due": 9_000.0, "waiting": 9_500.0})
    ran: list[str] = []
    daemon = HeartbeatDaemon(
        sessions_provider=lambda: sessions,
        run_heartbeat=lambda session: ran.append(session.session_id) or True,
        last_runs=last_runs,
        interval_seconds=300,
        wall_time=lambda: now,
    )

    with caplog.at_level(logging.INFO):
        summary = daemon.run_cycle()

    assert summary.enabled == 4
    assert summary.slated == 2
    assert summary.waiting == 1
    assert summary.first_time == 1
    assert summary.invalid == 1
    assert ran == ["first", "due"]
    assert last_runs.values["first"] == now
    assert last_runs.values["due"] == now
    assert "enabled=4 slated=2 waiting=1 first_time=1 invalid=1" in caplog.text


def test_failed_callback_does_not_advance_last_run(caplog) -> None:
    last_runs = MemoryLastRuns()

    def fail(_session: HeartbeatSession) -> None:
        raise RuntimeError("boom")

    daemon = HeartbeatDaemon(
        sessions_provider=lambda: [HeartbeatSession("s1", 5, "do work", "auto")],
        run_heartbeat=fail,
        last_runs=last_runs,
        interval_seconds=300,
        wall_time=lambda: 123.0,
    )

    with caplog.at_level(logging.ERROR):
        daemon.run_cycle()

    assert "s1" not in last_runs.values
    assert "Heartbeat run failed: session_id=s1" in caplog.text


def test_settings_change_wakes_daemon_and_logs(caplog) -> None:
    cycle_ran = threading.Event()
    daemon = HeartbeatDaemon(
        sessions_provider=lambda: cycle_ran.set() or [],
        run_heartbeat=lambda _session: True,
        last_runs=MemoryLastRuns(),
        interval_seconds=60,
    )

    with caplog.at_level(logging.INFO):
        daemon.start()
        daemon.settings_changed("s1")
        assert cycle_ran.wait(timeout=2)
        daemon.stop()

    assert "Heartbeat daemon started" in caplog.text
    assert "Heartbeat settings changed: session_id=s1" in caplog.text
    assert "Heartbeat daemon stopped" in caplog.text


def test_durable_last_run_map_is_loaded_and_write_through(monkeypatch) -> None:
    persisted: list[tuple[str, float]] = []
    monkeypatch.setattr(
        heartbeat_daemon, "load_heartbeat_last_runs", lambda: {"old": 10.0}
    )
    monkeypatch.setattr(
        heartbeat_daemon,
        "upsert_heartbeat_last_run",
        lambda session_id, unix_time: persisted.append((session_id, unix_time)),
    )

    last_runs = DurableLastRunMap()
    last_runs.record("new", 20.0)
    last_runs.discard("old")

    assert persisted == [("new", 20.0)]
    assert last_runs.snapshot() == {"new": 20.0}


def test_skipped_heartbeat_is_not_recorded() -> None:
    last_runs = MemoryLastRuns()
    daemon = HeartbeatDaemon(
        sessions_provider=lambda: [HeartbeatSession("s1", 5, "do work", "auto")],
        run_heartbeat=lambda _session: False,
        last_runs=last_runs,
        interval_seconds=300,
        wall_time=lambda: 123.0,
    )

    daemon.run_cycle()

    assert "s1" not in last_runs.values
