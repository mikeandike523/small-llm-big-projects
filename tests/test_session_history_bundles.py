"""Per-turn history loading and the event-model fixes it relies on."""

from __future__ import annotations

import pytest
from session_write_log import (
    EventLog,
    create,
    end_turn,
    install,
    set_title,
    start_turn,
    step,
    subturn,
)

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import (
    history_loader,
    session_db_load,
    session_writes,
)
from src.utils.session_events import replay_events
from src.utils.session_history_bundles import TurnBundleAssembler
from src.utils.session_model import (
    LLMExchange,
    Session,
    ToolCallRecord,
    turn_to_dict,
)


def _turn_starts(log: EventLog) -> list[tuple[int, str]]:
    return [(eid, tid) for tid, eid in log.starts().items()]


def _final(text: str) -> LLMExchange:
    return LLMExchange(assistant_content=text, is_final=True)


def _tool_step(call_id: str) -> LLMExchange:
    return LLMExchange(
        tool_calls=[ToolCallRecord(id=call_id, name="t", args={}, result="ok")]
    )


def _build_session(monkeypatch) -> tuple[Session, EventLog]:
    log = install(monkeypatch)
    s = Session(session_id="s1", startup_tool_calls=[{"name": "x"}])
    create(s)

    # t1: tool step, then answer.
    st1 = subturn("st1", "q1")
    t1 = start_turn(s, "t1", st1)
    step(s, st1, _tool_step("c1"))
    t1.todo_snapshot = [{"text": "a", "status": "closed"}]
    end_turn(s, t1, st1, _final("a1"))

    # t2, then a follow-up with a new title.
    st2 = subturn("st2", "q2")
    t2 = start_turn(s, "t2", st2)
    set_title(s, t2, "T2")
    end_turn(s, t2, st2, _final("a2"))
    st3 = subturn("st3", "follow-up")
    start_turn(s, "t2", st3, follow_up=True)
    assert log.commits[-1][0] == "turn_reopened"
    set_title(s, t2, "T2 revised")
    t2.todo_snapshot = [{"text": "b", "status": "closed"}]
    end_turn(s, t2, st3, _final("a3"))

    # t3, then a follow-up.
    st4 = subturn("st4", "q3")
    t3 = start_turn(s, "t3", st4)
    end_turn(s, t3, st4, _final("a4"))
    st5 = subturn("st5", "follow-up 2")
    start_turn(s, "t3", st5, follow_up=True)
    t3.todo_snapshot = [{"text": "c", "status": "closed"}]
    end_turn(s, t3, st5, _final("a5"))
    assert log.commits[-1][-1] == "turn_completed"

    # t4 still running, with an open todo item.
    st6 = subturn("st6", "q4")
    start_turn(s, "t4", st6)
    s.session_data["todo_list"] = [{"text": "a", "status": "open"}]
    step(s, st6, _tool_step("c2"))
    s.startup_done = True
    session_writes.write_startup_done("s1", s)
    return s, log


def _turns(session: Session) -> list[dict]:
    turns = list(session.completed_turns)
    if session.current_turn is not None:
        turns.append(session.current_turn)
    return [turn_to_dict(t) for t in turns]


def test_event_log_replays_to_the_in_memory_session(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
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


def test_a_repeated_write_writes_nothing_new(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
    before = len(log.rows)
    session_writes.write_step("s1", session, session.current_turn.subturns[0])
    assert len(log.rows) == before


def test_a_failed_write_is_repeated_by_the_next_one(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
    st = session.current_turn.subturns[0]

    def db_down(*args):
        raise RuntimeError("db down")

    monkeypatch.setattr(session_writes, "persist_save", db_down)
    with pytest.raises(RuntimeError):
        step(session, st, _tool_step("c3"))
    monkeypatch.setattr(session_writes, "persist_save", log.persist_save)
    step(session, st, _tool_step("c4"))

    assert log.commits[-1] == ["exchange_recorded", "exchange_recorded"]
    restored = replay_events("s1", log.rows)
    assert _turns(restored) == _turns(session)


def test_an_orphaned_turn_repair_rewrites_the_changed_exchanges(monkeypatch) -> None:
    _, log = _build_session(monkeypatch)
    # After a restart: t4 is still open, its written tool call has no result.
    loaded = replay_events("s1", log.rows)
    loaded.current_turn.subturns[0].exchanges[0].tool_calls[0].result = None

    assert session_writes.write_repaired_turn("s1", loaded) is True

    assert log.commits[-1] == [
        "exchange_recorded",
        "exchange_recorded",
        "turn_completed",
    ]
    restored = replay_events("s1", log.rows)
    assert restored.current_turn is None
    assert _turns(restored) == _turns(loaded)


def test_assembler_yields_each_turn_exactly_as_full_replay(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
    assembler = TurnBundleAssembler("s1", _turn_starts(log))
    bundles = []
    for row in log.rows:
        bundles.extend(assembler.feed(row))
    bundles.extend(assembler.finish())

    assert bundles == _turns(replay_events("s1", log.rows))
    assert assembler.warnings == []
    assert assembler.todo_list == [{"text": "a", "status": "open"}]


def test_assembler_flags_an_event_outside_its_turn_range(monkeypatch) -> None:
    _, log = _build_session(monkeypatch)
    # A late title for t1, written after t3 started (inside t3's id range).
    t3_start = dict((tid, eid) for eid, tid in _turn_starts(log))["t3"]
    straggler = {
        "id": t3_start,
        "event_type": "title_set",
        "payload": {"turn_id": "t1", "title": "late"},
    }
    rows = list(log.rows)
    rows.insert(t3_start, straggler)  # right after t3's turn_started row
    assembler = TurnBundleAssembler("s1", _turn_starts(log))
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


def _turn_index(log: EventLog, session: Session) -> list[dict]:
    """chat_turn_index rows matching the log (what saves would have written)."""
    turns = {t["id"]: t for t in _turns(session)}
    return [
        {
            "turn_seq": seq,
            "turn_id": tid,
            "start_event_id": eid,
            "title": turns[tid]["task_title"],
            "completed": turns[tid]["completed"],
        }
        for seq, (eid, tid) in enumerate(_turn_starts(log), 1)
    ]


def _wire_loader(
    monkeypatch, log, session, *, cached, page_size=500, running=True, unsaved=()
):
    """Point history_loader at the in-memory event log."""

    def fake_page(session_id, after_id, upto_id, limit):
        rows = [r for r in log.rows if after_id < r["id"] <= upto_id]
        return rows[:limit]

    def fake_latest(session_id, event_type, *, upto_id=None):
        rows = [
            r
            for r in log.rows
            if r["event_type"] == event_type and (upto_id is None or r["id"] <= upto_id)
        ]
        return rows[-1]["payload"] if rows else None

    index = _turn_index(log, session)

    def fake_latest_turn_upto(session_id, cutoff):
        rows = [r for r in index if r["start_event_id"] <= cutoff]
        return rows[-1] if rows else None

    def fake_turn_rows(session_id, first, last):
        return [r for r in index if first <= r["turn_seq"] <= last]

    def fake_seq_for_id(session_id, turn_id):
        return next((r["turn_seq"] for r in index if r["turn_id"] == turn_id), None)

    hl = history_loader
    monkeypatch.setattr(session_db_load, "_PAGE_SIZE", page_size)
    monkeypatch.setattr(session_db_load, "load_event_page", fake_page)
    monkeypatch.setattr(hl, "max_event_id", lambda sid: log.rows[-1]["id"])
    monkeypatch.setattr(
        hl,
        "load_history_flags",
        lambda sid: {"schema_version": 6, "history_cache_compatible": cached},
    )
    if cached:
        # The cached path must never fall back to the turn_started scan.
        monkeypatch.setattr(hl, "list_turn_starts", None)
    else:
        monkeypatch.setattr(hl, "list_turn_starts", lambda sid: _turn_starts(log))
    monkeypatch.setattr(hl, "latest_turn_upto", fake_latest_turn_upto)
    monkeypatch.setattr(hl, "load_turn_rows", fake_turn_rows)
    monkeypatch.setattr(hl, "turn_seq_for_turn_id", fake_seq_for_id)
    monkeypatch.setattr(hl, "load_latest_event_payload", fake_latest)
    monkeypatch.setattr(
        hl,
        "load_thinking_char_counts",
        lambda sid, ids: {"st1": (12, 3)} if "st1" in ids else {},
    )
    monkeypatch.setattr(hl, "get_watermark", lambda r, sid: "4-0")
    monkeypatch.setattr(hl, "get_events_since", lambda r, sid, w: list(unsaved))
    monkeypatch.setattr(hl._state, "_get_redis", lambda: object())
    monkeypatch.setattr(hl._state, "is_turn_reserved", lambda sid: running)
    monkeypatch.setattr(
        hl.runtime_settings, "persistence_lock", lambda sid: _FakeLock()
    )
    return hl


def _with_thinking(turn: dict) -> dict:
    for st in turn["subturns"]:
        st["native_thinking_chars"], st["irat_thinking_chars"] = (
            (12, 3) if st["id"] == "st1" else (0, 0)
        )
    return turn


@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize("page_size", [1, 3, 500])
def test_load_turn_returns_each_turn_exactly_as_full_replay(
    monkeypatch, page_size, cached
) -> None:
    session, log = _build_session(monkeypatch)
    hl = _wire_loader(monkeypatch, log, session, cached=cached, page_size=page_size)

    for page, expected in enumerate(_turns(session), 1):
        want = {
            "page": page,
            "turnId": expected["id"],
            "turn": _with_thinking(expected),
        }
        assert hl.load_turn_page("s1", page) == want
        assert hl.load_turn_by_id("s1", expected["id"]) == want


@pytest.mark.parametrize("cached", [True, False])
def test_load_turn_unknown_page_or_id_is_an_error(monkeypatch, cached) -> None:
    session, log = _build_session(monkeypatch)
    hl = _wire_loader(monkeypatch, log, session, cached=cached)
    assert "error" in hl.load_turn_by_id("s1", "nope")
    assert "error" in hl.load_turn_page("s1", 0)
    assert "error" in hl.load_turn_page("s1", 99)


@pytest.mark.parametrize("cached", [True, False])
def test_load_latest_turn_includes_running_state(monkeypatch, cached) -> None:
    session, log = _build_session(monkeypatch)
    unsaved = [{"id": "5-0", "type": "tool_call", "data": {"id": "c3"}}]
    hl = _wire_loader(monkeypatch, log, session, cached=cached, unsaved=unsaved)

    result = hl.load_latest_turn("s1")

    assert result["turnCount"] == 4
    assert result["latestTurnId"] == "t4"
    assert result["turn"] == _with_thinking(_turns(session)[-1])
    assert result["running"] is True
    assert result["events"] == unsaved
    assert [i["text"] for i in result["liveTodoItems"]] == ["a"]


def test_load_latest_turn_when_idle_has_no_live_state(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
    hl = _wire_loader(monkeypatch, log, session, cached=True, running=False)

    result = hl.load_latest_turn("s1")

    assert result["running"] is False
    assert result["events"] == []
    assert result["liveTodoItems"] is None


@pytest.mark.parametrize("cached", [True, False])
def test_load_latest_turn_of_an_empty_session(monkeypatch, cached) -> None:
    session = Session(session_id="s1")
    log = install(monkeypatch)
    create(session)
    hl = _wire_loader(monkeypatch, log, session, cached=cached, running=False)

    result = hl.load_latest_turn("s1")

    assert result["turnCount"] == 0
    assert result["latestTurnId"] is None
    assert result["turn"] is None


def test_events_are_not_replayed_without_a_bookmark(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
    unsaved = [{"id": "5-0", "type": "tool_call", "data": {"id": "c3"}}]
    hl = _wire_loader(monkeypatch, log, session, cached=True, unsaved=unsaved)
    monkeypatch.setattr(hl, "get_watermark", lambda r, sid: None)
    monkeypatch.setattr(hl, "latest_stream_id", lambda r, sid: "5-0")

    result = hl.load_latest_turn("s1")

    assert result["running"] is True
    assert result["events"] == []
    assert result["turn"] == _with_thinking(_turns(session)[-1])


def test_every_step_write_moves_the_bookmark(monkeypatch) -> None:
    _, log = _build_session(monkeypatch)
    # One per turn start, step and turn end; none for title/skills/startup.
    assert len(log.watermarks) == sum(
        1
        for commit in log.commits
        if commit[:1] in (["turn_started"], ["turn_reopened"], ["exchange_recorded"])
        or commit[-1:] == ["turn_completed"]
    )
