from __future__ import annotations

import threading
from types import SimpleNamespace

from src.ui_connector import (
    app as _app,
)  # noqa: F401 - establish application import order
from src.ui_connector.socket_handler_components import tool_execution
from src.utils.session_model import Session, Subturn, Turn

DENIAL = "Error: NOT Approved. User did not approve this action."


def _tool_call(call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id, name=f"tool_{call_id}", arguments={"id": call_id}
    )


def _run_batch(
    monkeypatch, approval_result, *, approval_target="tool_t1", cancel_event=None
):
    calls = [_tool_call("t1"), _tool_call("t2"), _tool_call("t3")]
    result = SimpleNamespace(tool_calls=calls)
    session = Session(session_id="session", initial_cwd=".")
    subturn = Subturn(id="subturn", user_text="test", user_text_with_context="test")
    turn = Turn(id="turn", subturns=[subturn])
    events: list[tuple[str, dict]] = []
    hook_order: list[str] = []

    monkeypatch.setattr(
        tool_execution.runtime_settings,
        "snapshot",
        lambda *_args: SimpleNamespace(approval_mode="default"),
    )
    monkeypatch.setattr(
        tool_execution,
        "_emit_and_log",
        lambda _session_id, event, data: events.append((event, data)),
    )

    def check_approval(name, *_args, **_kwargs):
        hook_order.append(f"approval:{name}")
        return name == approval_target, []

    def request_approval(*_args, **_kwargs):
        hook_order.append(f"dialog:{approval_target}")
        if callable(approval_result):
            return approval_result()
        return approval_result

    def dirty_effects(name, *_args, **_kwargs):
        hook_order.append(f"dirty:{name}")
        return {}, []

    def execute(name, *_args, **_kwargs):
        hook_order.append(f"execute:{name}")
        return f"result:{name}", []

    monkeypatch.setattr(tool_execution, "check_needs_approval", check_approval)
    monkeypatch.setattr(tool_execution, "_request_approval", request_approval)
    monkeypatch.setattr(tool_execution, "get_dirty_effects", dirty_effects)
    monkeypatch.setattr(tool_execution, "execute_tool", execute)
    monkeypatch.setattr(
        tool_execution, "_check_hop_paths_agree", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        tool_execution._dirty_cache, "check_requires_clean", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        tool_execution._dirty_cache, "apply_effects", lambda *_a, **_k: False
    )

    exchange = tool_execution._execute_tools(
        result,
        "",
        llm=None,
        session=session,
        session_id=session.session_id,
        current_turn=turn,
        cancel_event=cancel_event or threading.Event(),
        tool_map={},
        subturn_id=subturn.id,
    )
    return exchange, events, hook_order


def test_plain_denial_flushes_current_and_remaining_calls(monkeypatch) -> None:
    exchange, events, hook_order = _run_batch(monkeypatch, (False, None, False))

    assert [record.id for record in exchange.tool_calls] == ["t1", "t2", "t3"]
    assert [record.result for record in exchange.tool_calls] == [DENIAL] * 3
    assert hook_order == ["approval:tool_t1", "dialog:tool_t1"]
    assert [event for event, _data in events] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
    ]


def test_redirect_denial_repeats_identical_feedback(monkeypatch) -> None:
    exchange, _events, hook_order = _run_batch(
        monkeypatch, (False, "use the other file", False)
    )
    expected = f"{DENIAL} User suggests: use the other file"

    assert [record.result for record in exchange.tool_calls] == [expected] * 3
    assert hook_order == ["approval:tool_t1", "dialog:tool_t1"]


def test_denial_preserves_calls_that_already_executed(monkeypatch) -> None:
    exchange, _events, hook_order = _run_batch(
        monkeypatch, (False, None, False), approval_target="tool_t2"
    )

    assert [record.result for record in exchange.tool_calls] == [
        "result:tool_t1",
        DENIAL,
        DENIAL,
    ]
    assert hook_order == [
        "approval:tool_t1",
        "dirty:tool_t1",
        "execute:tool_t1",
        "approval:tool_t2",
        "dialog:tool_t2",
    ]


def test_approval_precedes_dirty_effects_and_batch_continues(monkeypatch) -> None:
    exchange, _events, hook_order = _run_batch(monkeypatch, (True, None, False))

    assert [record.result for record in exchange.tool_calls] == [
        "result:tool_t1",
        "result:tool_t2",
        "result:tool_t3",
    ]
    assert hook_order == [
        "approval:tool_t1",
        "dialog:tool_t1",
        "dirty:tool_t1",
        "execute:tool_t1",
        "approval:tool_t2",
        "dirty:tool_t2",
        "execute:tool_t2",
        "approval:tool_t3",
        "dirty:tool_t3",
        "execute:tool_t3",
    ]


def test_deny_and_stop_flushes_batch_before_cancellation(monkeypatch) -> None:
    cancel_event = threading.Event()

    def deny_and_stop(*_args, **_kwargs):
        cancel_event.set()
        return False, None, False

    exchange, _events, hook_order = _run_batch(
        monkeypatch, deny_and_stop, cancel_event=cancel_event
    )

    assert cancel_event.is_set()
    assert [record.result for record in exchange.tool_calls] == [DENIAL] * 3
    assert hook_order == ["approval:tool_t1", "dialog:tool_t1"]
