from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

# Establish the socket module import order used by the application.
import src.ui_connector.app  # noqa: F401
import src.ui_connector.socket_handler_components.approval as approval
import src.ui_connector.socket_handler_components.socket_events as socket_events
import src.ui_connector.socket_handler_components.socket_events_turn as turn_events
import src.ui_connector.socket_handler_components.state as state


def _wait_for_pending(session_id: str, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with state._pending_approvals_lock:
            pending = state._pending_approvals.get(session_id)
            if pending is not None:
                return pending
        time.sleep(0.01)
    raise AssertionError("approval was not registered")


def test_same_session_message_admission_is_atomic(monkeypatch):
    session_id = "atomic-admission"
    sid = "atomic-admission-sid"
    barrier = threading.Barrier(2)
    admitted: list[str] = []
    errors: list[dict] = []
    rejected = threading.Event()
    release_winner = threading.Event()
    original_try_reserve = state.try_reserve_turn

    def racing_try_reserve(candidate: str) -> bool:
        barrier.wait(timeout=2)
        return original_try_reserve(candidate)

    def admitted_handler(_data, admitted_session, _turn_id, _behavior):
        admitted.append(admitted_session)
        assert release_winner.wait(2)

    def capture_emit(event: str, payload: dict):
        if event == "error":
            errors.append(payload)
            rejected.set()

    monkeypatch.setattr(turn_events, "request", SimpleNamespace(sid=sid))
    monkeypatch.setattr(state, "try_reserve_turn", racing_try_reserve)
    monkeypatch.setattr(turn_events, "_handle_admitted_user_message", admitted_handler)
    monkeypatch.setattr(turn_events, "emit", capture_emit)
    monkeypatch.setitem(state._sid_to_session_id, sid, session_id)

    failures: list[BaseException] = []

    def invoke() -> None:
        try:
            turn_events.handle_user_message(
                {"text": "hello", "followup_behavior": "new-task"}
            )
        except BaseException as exc:  # surfaced below from worker threads
            failures.append(exc)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert rejected.wait(2)
        release_winner.set()
        for thread in threads:
            thread.join(timeout=2)

        assert not failures
        assert admitted == [session_id]
        assert len(errors) == 1
        assert not state.is_turn_reserved(session_id)
    finally:
        release_winner.set()
        state.release_turn(session_id)


def test_turn_reservation_is_released_when_admitted_handler_fails(monkeypatch):
    session_id = "admission-error"
    sid = "admission-error-sid"
    monkeypatch.setattr(turn_events, "request", SimpleNamespace(sid=sid))
    monkeypatch.setitem(state._sid_to_session_id, sid, session_id)

    def fail(*_args):
        raise RuntimeError("setup failed")

    monkeypatch.setattr(turn_events, "_handle_admitted_user_message", fail)
    try:
        with pytest.raises(RuntimeError, match="setup failed"):
            turn_events.handle_user_message({"text": "hello"})
        assert not state.is_turn_reserved(session_id)
        assert state.try_reserve_turn(session_id)
    finally:
        state.release_turn(session_id)


def test_different_sessions_can_be_reserved_concurrently():
    session_ids = ("parallel-a", "parallel-b")
    barrier = threading.Barrier(2)
    results: dict[str, bool] = {}

    def reserve(session_id: str) -> None:
        barrier.wait(timeout=2)
        results[session_id] = state.try_reserve_turn(session_id)

    threads = [threading.Thread(target=reserve, args=(value,)) for value in session_ids]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        assert results == {"parallel-a": True, "parallel-b": True}
    finally:
        for session_id in session_ids:
            state.release_turn(session_id)


def _start_approval(monkeypatch, session_id: str, tool_id: str, turn_id: str):
    result: list[tuple[bool, str | None, bool]] = []
    monkeypatch.setattr(approval, "_emit_and_log", lambda *_args, **_kwargs: None)

    def request_approval() -> None:
        result.append(
            approval._request_approval(
                session_id,
                tool_id,
                "test_tool",
                {},
                turn_id=turn_id,
            )
        )

    thread = threading.Thread(target=request_approval)
    thread.start()
    _wait_for_pending(session_id)
    return thread, result


def _configure_approval_handler(monkeypatch, session_id: str) -> None:
    sid = f"{session_id}-sid"
    monkeypatch.setattr(socket_events, "request", SimpleNamespace(sid=sid))
    monkeypatch.setattr(socket_events, "_emit_and_log", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(state._sid_to_session_id, sid, session_id)


def test_approval_response_requires_matching_turn_and_tool(monkeypatch):
    session_id = "approval-correlation"
    _configure_approval_handler(monkeypatch, session_id)
    thread, result = _start_approval(monkeypatch, session_id, "tool-1", "turn-1")
    try:
        socket_events.handle_approval_response(
            {"id": "stale-tool", "turn_id": "turn-1", "approved": True}
        )
        socket_events.handle_approval_response(
            {"id": "tool-1", "turn_id": "stale-turn", "approved": True}
        )
        assert thread.is_alive()

        socket_events.handle_approval_response(
            {"id": "tool-1", "turn_id": "turn-1", "approved": True}
        )
        thread.join(timeout=2)
        assert result == [(True, None, False)]
    finally:
        with state._pending_approvals_lock:
            pending = state._pending_approvals.pop(session_id, None)
        if pending:
            pending["event"].set()


def test_second_pending_approval_cannot_overwrite_first(monkeypatch):
    session_id = "approval-overwrite"
    _configure_approval_handler(monkeypatch, session_id)
    thread, result = _start_approval(monkeypatch, session_id, "tool-1", "turn-1")
    try:
        with pytest.raises(RuntimeError, match="already pending"):
            approval._request_approval(
                session_id,
                "tool-2",
                "test_tool",
                {},
                turn_id="turn-1",
            )
        with state._pending_approvals_lock:
            assert state._pending_approvals[session_id]["tool_id"] == "tool-1"

        socket_events.handle_approval_response(
            {"id": "tool-1", "turn_id": "turn-1", "approved": False}
        )
        thread.join(timeout=2)
        assert result == [(False, None, False)]
    finally:
        with state._pending_approvals_lock:
            pending = state._pending_approvals.pop(session_id, None)
        if pending:
            pending["event"].set()


def test_duplicate_response_does_not_resolve_later_approval(monkeypatch):
    session_id = "approval-duplicate"
    _configure_approval_handler(monkeypatch, session_id)
    first_thread, first_result = _start_approval(
        monkeypatch, session_id, "tool-1", "turn-1"
    )
    socket_events.handle_approval_response(
        {"id": "tool-1", "turn_id": "turn-1", "approved": True}
    )
    first_thread.join(timeout=2)
    assert first_result == [(True, None, False)]

    second_thread, second_result = _start_approval(
        monkeypatch, session_id, "tool-2", "turn-2"
    )
    try:
        socket_events.handle_approval_response(
            {"id": "tool-1", "turn_id": "turn-1", "approved": False}
        )
        assert second_thread.is_alive()

        socket_events.handle_approval_response(
            {"id": "tool-2", "turn_id": "turn-2", "approved": True}
        )
        second_thread.join(timeout=2)
        assert second_result == [(True, None, False)]
    finally:
        with state._pending_approvals_lock:
            pending = state._pending_approvals.pop(session_id, None)
        if pending:
            pending["event"].set()


def test_approval_waiter_does_not_remove_entry_it_does_not_own(monkeypatch):
    session_id = "approval-identity"
    thread, result = _start_approval(monkeypatch, session_id, "tool-1", "turn-1")
    with state._pending_approvals_lock:
        original = state._pending_approvals[session_id]
        replacement = {
            "event": threading.Event(),
            "approved": None,
            "redirect_message": None,
            "turn_id": "turn-2",
            "subturn_id": "subturn-2",
            "tool_id": "tool-2",
            "cancel_event": None,
        }
        state._pending_approvals[session_id] = replacement

    original["approved"] = False
    original["event"].set()
    thread.join(timeout=2)
    try:
        assert result == [(False, None, False)]
        with state._pending_approvals_lock:
            assert state._pending_approvals[session_id] is replacement
    finally:
        with state._pending_approvals_lock:
            state._pending_approvals.pop(session_id, None)
