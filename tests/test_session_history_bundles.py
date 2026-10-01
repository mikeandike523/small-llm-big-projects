"""Streaming per-turn history bundles and the event-model fixes they rely on."""

from __future__ import annotations

import json

import pytest

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import history_loader
from src.ui_connector.socket_handler_components._session_event_emit import (
    compute_events,
)
from src.utils.session_events import replay_events
from src.utils.session_history_bundles import TurnBundleAssembler
from src.utils.session_model import (
    LLMExchange,
    Session,
    Subturn,
    ToolCallRecord,
    Turn,
    turn_to_dict,
)


class _EventLog:
    """Accumulates compute_events output across saves, like session_events."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.cursor: dict = {}

    def save(self, session: Session) -> list[str]:
        events = compute_events(session, self.cursor)
        for event_type, payload in events:
            self.rows.append(
                {
                    "id": len(self.rows) + 1,
                    "event_type": event_type,
                    "payload": json.loads(json.dumps(payload)),
                }
            )
        return [event_type for event_type, _ in events]

    def turn_starts(self) -> list[tuple[int, str]]:
        return [
            (row["id"], row["payload"]["turn_id"])
            for row in self.rows
            if row["event_type"] == "turn_started"
        ]


def _st(sid: str, text: str) -> Subturn:
    return Subturn(id=sid, user_text=text, user_text_with_context=text)


def _final(text: str) -> LLMExchange:
    return LLMExchange(assistant_content=text, is_final=True)


def _tool_step(call_id: str) -> LLMExchange:
    return LLMExchange(
        tool_calls=[ToolCallRecord(id=call_id, name="t", args={}, result="ok")]
    )


def _complete(session: Session, turn: Turn, todo: list) -> None:
    turn.completed = True
    turn.todo_snapshot = todo
    session.completed_turns.append(turn)
    session.current_turn = None


def _reopen(session: Session, subturn: Subturn) -> Turn:
    turn = session.completed_turns.pop()
    turn.completed = False
    turn.subturns.append(subturn)
    session.current_turn = turn
    return turn


def _build_session() -> tuple[Session, _EventLog]:
    s = Session(session_id="s1", startup_tool_calls=[{"name": "x"}])
    log = _EventLog()
    log.save(s)

    # t1: tool step, then answer.
    t1 = Turn(id="t1", subturns=[_st("st1", "q1")])
    s.current_turn = t1
    log.save(s)
    t1.subturns[0].exchanges.append(_tool_step("c1"))
    s.session_data["todo_list"] = [{"text": "a", "status": "open"}]
    log.save(s)
    t1.subturns[0].exchanges.append(_final("a1"))
    _complete(s, t1, [{"text": "a", "status": "closed"}])
    log.save(s)

    # t2, then a follow-up that is saved while reopened, with a new title.
    t2 = Turn(id="t2", subturns=[_st("st2", "q2")], task_title="T2")
    s.current_turn = t2
    log.save(s)
    t2.subturns[0].exchanges.append(_final("a2"))
    _complete(s, t2, [])
    log.save(s)
    t2 = _reopen(s, _st("st3", "follow-up"))
    assert "turn_reopened" in log.save(s)
    t2.subturns[1].exchanges.append(_final("a3"))
    t2.task_title = "T2 revised"
    _complete(s, t2, [{"text": "b", "status": "closed"}])
    log.save(s)

    # t3, then a follow-up that completes with no save in between.
    t3 = Turn(id="t3", subturns=[_st("st4", "q3")])
    s.current_turn = t3
    t3.subturns[0].exchanges.append(_final("a4"))
    _complete(s, t3, [])
    log.save(s)
    t3 = _reopen(s, _st("st5", "follow-up 2"))
    t3.subturns[1].exchanges.append(_final("a5"))
    _complete(s, t3, [{"text": "c", "status": "closed"}])
    assert "turn_completed" in log.save(s)

    # t4 still running.
    t4 = Turn(id="t4", subturns=[_st("st6", "q4")])
    s.current_turn = t4
    t4.subturns[0].exchanges.append(_tool_step("c2"))
    s.startup_done = True
    log.save(s)
    return s, log


def _turns(session: Session) -> list[dict]:
    turns = list(session.completed_turns)
    if session.current_turn is not None:
        turns.append(session.current_turn)
    return [turn_to_dict(t) for t in turns]


def test_event_log_replays_to_the_in_memory_session() -> None:
    session, log = _build_session()
    restored = replay_events("s1", log.rows)

    assert _turns(restored) == _turns(session)
    assert restored.startup_done is True
    assert restored.current_turn.id == "t4"
    t2 = restored.completed_turns[1]
    assert t2.task_title == "T2 revised"
    assert t2.todo_snapshot == [{"text": "b", "status": "closed"}]
    assert restored.completed_turns[2].todo_snapshot == [
        {"text": "c", "status": "closed"}
    ]


def test_saves_after_completion_emit_nothing() -> None:
    session, log = _build_session()
    assert log.save(session) == []


def test_assembler_yields_each_turn_exactly_as_full_replay() -> None:
    session, log = _build_session()
    assembler = TurnBundleAssembler("s1", log.turn_starts())
    bundles = []
    for row in log.rows:
        bundles.extend(assembler.feed(row))
    bundles.extend(assembler.finish())

    assert bundles == _turns(replay_events("s1", log.rows))
    assert assembler.warnings == []
    assert assembler.todo_list == [{"text": "a", "status": "open"}]


def test_assembler_flags_an_event_outside_its_turn_range() -> None:
    _, log = _build_session()
    # A late title for t1, written after t3 started (inside t3's id range).
    t3_start = dict((tid, eid) for eid, tid in log.turn_starts())["t3"]
    straggler = {
        "id": t3_start,
        "event_type": "title_set",
        "payload": {"turn_id": "t1", "title": "late"},
    }
    rows = list(log.rows)
    rows.insert(t3_start, straggler)  # right after t3's turn_started row
    assembler = TurnBundleAssembler("s1", log.turn_starts())
    bundles = []
    for row in rows:
        bundles.extend(assembler.feed(row))
    bundles.extend(assembler.finish())

    assert [b["id"] for b in bundles] == ["t1", "t2", "t3", "t4"]
    assert bundles[0]["task_title"] is None
    assert any("already-sent" in w for w in assembler.warnings)


class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("page_size", [1, 3, 200])
def test_worker_streams_bundles_and_unsaved_events(monkeypatch, page_size) -> None:
    session, log = _build_session()
    cutoff = log.rows[-1]["id"]
    sent: list[tuple[str, dict]] = []

    def fake_emit(event, data, to=None, callback=None):
        sent.append((event, data))
        if callback is not None:
            callback()

    def fake_page(session_id, after_id, upto_id, limit):
        rows = [r for r in log.rows if after_id < r["id"] <= upto_id]
        return rows[:limit]

    unsaved = [{"id": "5-0", "type": "tool_call", "data": {"id": "c3"}}]
    hl = history_loader
    monkeypatch.setattr(hl, "_PAGE_SIZE", page_size)
    monkeypatch.setattr(hl.socketio, "emit", fake_emit)
    monkeypatch.setattr(hl, "max_event_id", lambda sid: cutoff)
    monkeypatch.setattr(hl, "list_turn_starts", lambda sid: log.turn_starts())
    monkeypatch.setattr(hl, "load_event_page", fake_page)
    monkeypatch.setattr(hl, "load_session_meta", lambda sid: {"schema_version": 6})
    monkeypatch.setattr(hl, "load_thinking_char_counts", lambda sid: {"st1": (12, 3)})
    monkeypatch.setattr(hl, "get_watermark", lambda r, sid: "4-0")
    monkeypatch.setattr(hl, "get_events_since", lambda r, sid, w: unsaved)
    monkeypatch.setattr(hl._state, "_get_redis", lambda: object())
    monkeypatch.setattr(hl._state, "is_turn_reserved", lambda sid: True)
    monkeypatch.setattr(
        hl.runtime_settings, "persistence_lock", lambda sid: _FakeLock()
    )

    hl._stream_history("sid1", "s1", "load1", hl.threading.Event())

    assert sent[0] == (
        "history_load_started",
        {"loadId": "load1", "turnIds": ["t1", "t2", "t3", "t4"], "running": True},
    )
    bundles = [d for e, d in sent if e == "history_turn_bundle"]
    assert [b["seq"] for b in bundles] == [0, 1, 2, 3]
    expected = _turns(session)
    for turn in expected:
        for st in turn["subturns"]:
            st["native_thinking_chars"], st["irat_thinking_chars"] = (
                (12, 3) if st["id"] == "st1" else (0, 0)
            )
    assert [b["turn"] for b in bundles] == expected
    done_event, done = sent[-1]
    assert done_event == "history_load_done"
    assert done["events"] == unsaved
    assert done["liveTodoItems"] is not None
