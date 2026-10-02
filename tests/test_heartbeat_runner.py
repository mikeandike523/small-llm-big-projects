from __future__ import annotations

import logging
import threading

from src.ui_connector.heartbeat_daemon import HeartbeatSession
from src.ui_connector.heartbeat_runner import HeartbeatRunner
from src.utils.session_model import SUBTURN_ORIGIN_HEARTBEAT, SUBTURN_ORIGIN_USER


class Harness:
    """Scripted launch results and running-turn owners, with a call log."""

    def __init__(self, launches: list[bool], owners: list[str | None]) -> None:
        self.launches = iter(launches)
        self.owners = iter(owners)
        self.calls: list[tuple] = []
        self.recorded: list[str] = []
        self.runner = HeartbeatRunner(
            launch=self._launch,
            running_turn_owner=lambda _sid: next(self.owners),
            cancel=lambda sid: self.calls.append(("cancel", sid)),
            record_run=self.recorded.append,
            retry_seconds=0,
        )

    def _launch(self, session_id: str, text: str) -> bool:
        self.calls.append(("launch", session_id, text))
        return next(self.launches)


def _session(instructions: str = "do work") -> HeartbeatSession:
    return HeartbeatSession("s1", 5, instructions)


def test_idle_session_launches_trimmed_instructions(caplog) -> None:
    h = Harness([True], [])
    with caplog.at_level(logging.INFO):
        assert h.runner(_session("  do work \n")) is True
    assert h.calls == [("launch", "s1", "do work")]
    assert "Heartbeat launched: session_id=s1" in caplog.text


def test_user_owned_turn_is_skipped_without_cancel(caplog) -> None:
    h = Harness([False], [SUBTURN_ORIGIN_USER])
    with caplog.at_level(logging.INFO):
        assert h.runner(_session()) is False
    assert h.calls == [("launch", "s1", "do work")]
    assert h.recorded == []
    assert "has a running user turn" in caplog.text
    # Skipping releases the session so the next cycle can try again.
    h2_launches = iter([True])
    h.runner._launch = lambda _sid, _text: next(h2_launches)
    assert h.runner(_session()) is True


def test_heartbeat_owned_turn_is_cancelled_then_launched(caplog) -> None:
    h = Harness([False, True], [SUBTURN_ORIGIN_HEARTBEAT])
    with caplog.at_level(logging.INFO):
        assert h.runner.cancel_and_retry("s1", "work")
    assert h.calls == [
        ("cancel", "s1"),
        ("launch", "s1", "work"),
        ("cancel", "s1"),
        ("launch", "s1", "work"),
    ]
    assert h.recorded == ["s1"]
    assert "attempt 2/3" in caplog.text
    assert "attempt 3/3" not in caplog.text


def test_retry_stops_without_cancel_when_user_takes_over(caplog) -> None:
    h = Harness([False], [SUBTURN_ORIGIN_USER])
    with caplog.at_level(logging.INFO):
        assert not h.runner.cancel_and_retry("s1", "work")
    assert h.calls == [("cancel", "s1"), ("launch", "s1", "work")]
    assert h.recorded == []
    assert "has a running user turn" in caplog.text


def test_heartbeat_turn_still_busy_after_three_cancels_is_orphaned(caplog) -> None:
    h = Harness([False] * 3, [SUBTURN_ORIGIN_HEARTBEAT] * 3)
    with caplog.at_level(logging.INFO):
        assert not h.runner.cancel_and_retry("s1", "work")
    assert [c[0] for c in h.calls].count("cancel") == 3
    assert h.recorded == ["s1"]
    assert "orphaned" in caplog.text
    assert "Restarting the SLBP server is recommended" in caplog.text


def test_busy_heartbeat_turn_is_handed_to_background_retry() -> None:
    launched = threading.Event()
    results = iter([False, True])
    owners = iter([SUBTURN_ORIGIN_HEARTBEAT])

    def launch(_sid: str, _text: str) -> bool:
        ok = next(results)
        if ok:
            launched.set()
        return ok

    recorded: list[str] = []
    runner = HeartbeatRunner(
        launch=launch,
        running_turn_owner=lambda _sid: next(owners),
        cancel=lambda _sid: None,
        record_run=recorded.append,
        retry_seconds=0,
    )
    # Not recorded by the daemon: the retry thread records it itself.
    assert runner(_session()) is False
    assert launched.wait(2)


def test_turn_ending_between_launch_and_owner_check_retries_once() -> None:
    h = Harness([False, True], [None])
    assert h.runner(_session()) is True
    assert [c[0] for c in h.calls] == ["launch", "launch"]


def test_blank_instructions_are_logged_invalid_and_skipped(caplog) -> None:
    h = Harness([], [])
    with caplog.at_level(logging.WARNING):
        assert h.runner(_session(" \n\t ")) is False
    assert h.calls == []
    assert "Heartbeat invalid: session_id=s1" in caplog.text


def test_shutdown_aborts_retry_wait() -> None:
    h = Harness([], [])
    h.runner._retry_seconds = 60
    h.runner.shutdown()
    assert not h.runner.cancel_and_retry("s1", "work")
    assert h.calls == [("cancel", "s1")]
    assert h.recorded == []


def test_heartbeat_message_uses_auto_followup_detection(monkeypatch) -> None:
    import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
    from src.ui_connector import heartbeat_runner
    from src.ui_connector.socket_handler_components import socket_events_turn

    seen = {}

    def fake_new_user_message(session_id, data, turn_id, behavior, **kwargs):
        seen.update(session_id=session_id, data=data, behavior=behavior, **kwargs)
        return True

    monkeypatch.setattr(socket_events_turn, "new_user_message", fake_new_user_message)
    assert heartbeat_runner._launch_heartbeat("s1", "check build")
    assert seen == {
        "session_id": "s1",
        "data": {"text": "check build"},
        "behavior": "auto",
        "background": True,
        "origin": SUBTURN_ORIGIN_HEARTBEAT,
    }
