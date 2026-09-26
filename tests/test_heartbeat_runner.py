from __future__ import annotations

import logging
import threading

from src.ui_connector.heartbeat_daemon import HeartbeatSession
from src.ui_connector.heartbeat_runner import HeartbeatRunner


def _runner(launch_results: list[bool], calls: list[tuple], **kwargs):
    results = iter(launch_results)

    def launch(session_id: str, text: str) -> bool:
        calls.append(("launch", session_id, text))
        return next(results)

    def cancel(session_id: str) -> None:
        calls.append(("cancel", session_id))

    return HeartbeatRunner(launch=launch, cancel=cancel, retry_seconds=0, **kwargs)


def test_idle_session_launches_trimmed_instructions(caplog) -> None:
    calls: list[tuple] = []
    runner = _runner([True], calls)
    with caplog.at_level(logging.INFO):
        assert runner.fire("s1", "do work")
    assert calls == [("launch", "s1", "do work")]
    assert "Heartbeat launched: session_id=s1" in caplog.text


def test_busy_session_is_cancelled_then_launched(caplog) -> None:
    calls: list[tuple] = []
    runner = _runner([False, False, True], calls)
    with caplog.at_level(logging.INFO):
        assert runner.fire("s1", "work")
    assert calls == [
        ("launch", "s1", "work"),
        ("cancel", "s1"),
        ("launch", "s1", "work"),
        ("cancel", "s1"),
        ("launch", "s1", "work"),
    ]
    assert "attempt 2/3" in caplog.text
    assert "Heartbeat launched" in caplog.text


def test_session_busy_after_three_cancels_is_reported_orphaned(caplog) -> None:
    calls: list[tuple] = []
    runner = _runner([False] * 4, calls)
    with caplog.at_level(logging.INFO):
        assert not runner.fire("s1", "work")
    assert [c[0] for c in calls].count("cancel") == 3
    assert [c[0] for c in calls].count("launch") == 4
    assert "orphaned" in caplog.text
    assert "Restarting the SLBP server is recommended" in caplog.text


def test_blank_instructions_are_logged_invalid_and_skipped(caplog) -> None:
    calls: list[tuple] = []
    runner = _runner([], calls)
    with caplog.at_level(logging.WARNING):
        runner(HeartbeatSession("s1", 5, " \n\t "))
    assert calls == []
    assert "Heartbeat invalid: session_id=s1" in caplog.text


def test_callback_trims_and_fires_in_background() -> None:
    launched = threading.Event()
    seen: list[str] = []

    def launch(_session_id: str, text: str) -> bool:
        seen.append(text)
        launched.set()
        return True

    runner = HeartbeatRunner(launch=launch, cancel=lambda _s: None)
    runner(HeartbeatSession("s1", 5, "  do work \n"))
    assert launched.wait(2)
    assert seen == ["do work"]


def test_shutdown_aborts_retry_wait() -> None:
    calls: list[tuple] = []
    runner = _runner([False], calls)
    runner._retry_seconds = 60
    runner.shutdown()
    assert not runner.fire("s1", "work")
    assert calls == [("launch", "s1", "work"), ("cancel", "s1")]
