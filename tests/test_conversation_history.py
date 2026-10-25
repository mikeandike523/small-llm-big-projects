"""Interrupted and empty turns are filled in when history is built, never stored.

conversation_history.py is the one place past turns become conversation. These
tests check its rules, that every reader (LLM payload, skill selector,
continuation detector, title context) goes through it, that a cache-built
session reads exactly like a full replay, and that loading a session whose
last turn was cut off writes nothing.
"""

from __future__ import annotations

import asyncio

import pytest
from session_write_log import (
    create,
    end_turn,
    install,
    start_turn,
    step,
    subturn,
    wire_session_load,
)

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import session_db_load, watchdogs
from src.ui_connector.socket_handler_components.llm import _build_llm_payload
from src.ui_connector.socket_handler_components.socket_events_turn import (
    _build_title_context,
)
from src.utils.conversation_history import (
    INTERRUPTED_ANSWER,
    INTERRUPTED_TOOL_RESULT,
    NO_RESPONSE,
    NO_USER_MESSAGE,
    closed_history,
    closed_subturn,
)
from src.utils.session_model import (
    LLMExchange,
    Session,
    Subturn,
    ToolCallRecord,
    Turn,
)


def _final(text: str) -> LLMExchange:
    return LLMExchange(assistant_content=text, is_final=True)


def _tool_step(call_id: str, result: str | None = "ok") -> LLMExchange:
    return LLMExchange(
        assistant_content="looking",
        tool_calls=[ToolCallRecord(id=call_id, name="t", args={}, result=result)],
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _closed(user: str, exchanges: list[LLMExchange], context: str | None = None):
    st = Subturn(
        id="st",
        user_text=user,
        user_text_with_context=user if context is None else context,
        exchanges=exchanges,
    )
    return closed_subturn(Turn(id="t", subturns=[st]), st)


@pytest.mark.parametrize(
    "user, exchanges, expected",
    [
        ("q", [_tool_step("c"), _final("a")], ("q", "a", False)),
        ("q", [_tool_step("c")], ("q", INTERRUPTED_ANSWER, True)),
        ("q", [], ("q", INTERRUPTED_ANSWER, True)),
        ("q", [_final("  ")], ("q", NO_RESPONSE, False)),
        ("", [_final("a")], (NO_USER_MESSAGE, "a", False)),
        # The last final exchange wins, later non-final steps are ignored.
        ("q", [_final("a"), _tool_step("c")], ("q", "a", False)),
    ],
)
def test_closed_subturn_rules(user, exchanges, expected) -> None:
    cs = _closed(user, exchanges)
    assert (cs.user_context, cs.answer, cs.interrupted) == expected


def test_a_subturn_with_nothing_recorded_is_skipped() -> None:
    assert _closed("", []) is None
    assert _closed("", [_tool_step("c")]) is None
    assert _closed("  ", [_final("")]) is None


def test_user_text_falls_back_to_the_context_text() -> None:
    cs = _closed("", [_final("a")], context="[ctx] q")
    assert (cs.user_text, cs.user_context) == ("[ctx] q", "[ctx] q")


def test_a_tool_call_without_a_result_is_paired_explicitly() -> None:
    msgs = _tool_step("c", result=None).to_messages()
    assert msgs[1] == {
        "role": "tool",
        "tool_call_id": "c",
        "content": INTERRUPTED_TOOL_RESULT,
    }


# ---------------------------------------------------------------------------
# A session with every odd case, loaded from the cache and from full replay
# ---------------------------------------------------------------------------


def _load(monkeypatch, log, *, cached: bool) -> Session:
    wire_session_load(monkeypatch, log, cached=cached)
    before = len(log.rows)
    session = session_db_load.load_session_from_db("s1")
    assert len(log.rows) == before  # loading never writes
    return session


def _build_odd_session(monkeypatch):
    log = install(monkeypatch)
    s = Session(session_id="s1", initial_cwd="/w")
    create(s)

    # t1: a normal answer with Context Notes.
    st = subturn("st1", "q1")
    t1 = start_turn(s, "t1", st)
    step(s, st, _tool_step("c1"))
    st.detailed_summary = "notes 1"
    end_turn(s, t1, st, _final("a1"))

    # t2: the server stops mid-tool (the tool call never got a result).
    st = subturn("st2", "q2")
    start_turn(s, "t2", st)
    step(s, st, _tool_step("c2", result=None))
    s = _load(monkeypatch, log, cached=True)
    assert s.current_turn is None and s.completed_turns[-1].id == "t2"

    # t3: the model's final answer was empty.
    st = subturn("st3", "q3")
    t3 = start_turn(s, "t3", st)
    end_turn(s, t3, st, _final(""))

    # t4: nothing recorded at all (cut off right after it started).
    start_turn(s, "t4", subturn("st4", ""))
    s = _load(monkeypatch, log, cached=True)

    # t5: an answer without user text.
    st = subturn("st5", "")
    t5 = start_turn(s, "t5", st)
    end_turn(s, t5, st, _final("a5"))

    # t6: cut off, then a follow-up on the same turn that completes.
    st = subturn("st6", "q6")
    start_turn(s, "t6", st)
    step(s, st, _tool_step("c6"))
    s = _load(monkeypatch, log, cached=True)
    st = subturn("st7", "and then?")
    t6 = start_turn(s, "t6", st, follow_up=True)
    assert log.commits[-1][:2] == ["turn_reopened", "subturn_started"]
    end_turn(s, t6, st, _final("a7"))

    # t7 and t8 plain, so t1-t6 are sealed (stubs) in the cache-built load.
    for tid in ("t7", "t8"):
        st = subturn(f"st-{tid}", f"q-{tid}")
        turn = start_turn(s, tid, st)
        end_turn(s, turn, st, _final(f"a-{tid}"))
    return log


def _readers(monkeypatch, session: Session) -> dict:
    new_turn = Turn(id="new", subturns=[subturn("stN", "next question")])
    asked: list = []
    monkeypatch.setattr(
        watchdogs,
        "_call_sampler",
        lambda llm, messages, params, **kw: asked.append(messages)
        or type("R", (), {"content": "NO"})(),
    )
    asyncio.run(watchdogs._is_continuation(None, session, "next question", {}))
    return {
        "payload": _build_llm_payload(session, new_turn),
        "skills": watchdogs._build_skill_selector_transcript(session, new_turn),
        "title": _build_title_context(session, new_turn),
        "continuation": asked[0][1]["content"],
        "history": closed_history(session),
    }


def test_cache_built_and_full_replay_read_the_same(monkeypatch) -> None:
    log = _build_odd_session(monkeypatch)
    cached = _load(monkeypatch, log, cached=True)
    full = _load(monkeypatch, log, cached=False)
    assert any(t.from_cache for t in cached.completed_turns)
    assert _readers(monkeypatch, cached) == _readers(monkeypatch, full)


def test_odd_turns_are_filled_in(monkeypatch) -> None:
    log = _build_odd_session(monkeypatch)
    history = {
        cs.subturn_id: cs for cs in closed_history(_load(monkeypatch, log, cached=True))
    }

    assert "st4" not in history  # nothing recorded: skipped
    assert history["st1"].answer == "a1" and history["st1"].notes == "notes 1"
    assert history["st2"].answer == INTERRUPTED_ANSWER and history["st2"].interrupted
    assert history["st3"].answer == NO_RESPONSE
    assert history["st5"].user_context == NO_USER_MESSAGE
    assert history["st6"].answer == INTERRUPTED_ANSWER
    assert history["st7"].answer == "a7"
    # The cut-off turns stay exactly as written.
    starts = [r for r in log.rows if r["event_type"] == "turn_completed"]
    assert {r["payload"]["turn_id"] for r in starts} == {
        "t1",
        "t3",
        "t5",
        "t6",
        "t7",
        "t8",
    }


def test_llm_payload_never_sends_empty_or_unpaired_messages(monkeypatch) -> None:
    log = _build_odd_session(monkeypatch)
    session = _load(monkeypatch, log, cached=False)
    live = subturn("stN", "next question")
    live.exchanges.append(_tool_step("cN", result=None))
    payload = _build_llm_payload(session, Turn(id="new", subturns=[live]))

    body = payload[1:]
    assert all(m.get("content") or m.get("tool_calls") for m in body)
    closed = body[:-3]  # the live subturn: user, assistant tool call, tool
    assert [m["role"] for m in closed] == ["user", "assistant"] * (len(closed) // 2)
    assert body[-1]["content"] == INTERRUPTED_TOOL_RESULT
