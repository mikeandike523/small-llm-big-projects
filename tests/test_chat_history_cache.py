"""Chat history cache (migration v18): cache-built sessions match full replay.

A session loaded from `chat_turn_index` / `chat_history_cache` (sealed turns
as stubs, the last two turns replayed from events) must give every reader of
the conversation exactly what a full event-log replay gives, and writing to it
must never write the stubs back. The live write path and the backfill must
produce identical cache rows.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from session_write_log import (
    EventLog,
    wire_cache_db,
    create,
    end_turn,
    install,
    set_title,
    start_turn,
    step,
    subturn,
)

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.cli_routes import intense_migration
from src.ui_connector.socket_handler_components import (
    runtime_settings,
    session_db_load,
    session_writes,
    setting_events,
)
from src.ui_connector.socket_handler_components._session_event_emit import (
    cache_rows_for_save,
)
from src.ui_connector.socket_handler_components.llm import _build_llm_payload
from src.ui_connector.socket_handler_components.socket_events_turn import (
    _build_title_context,
)
from src.ui_connector.socket_handler_components.watchdogs import (
    _build_skill_selector_transcript,
)
from src.utils import session_cache_backfill
from src.utils.session_cache_projection import (
    project_turn,
    stub_turn_from_cache,
)
from src.utils.conversation_history import final_answer
from src.utils.session_events import (
    SESSION_LEVEL_EVENT_TYPES,
    derive_meta,
    replay_events,
)
from src.utils.session_model import (
    LLMExchange,
    Session,
    ToolCallRecord,
    Turn,
    turn_to_dict,
)


def _final(text: str) -> LLMExchange:
    return LLMExchange(assistant_content=text, is_final=True)


def _tool_step(call_id: str) -> LLMExchange:
    return LLMExchange(
        assistant_content="looking",
        tool_calls=[ToolCallRecord(id=call_id, name="t", args={}, result="big output")],
    )


def _change_settings(session: Session, approval_mode: str, profile: str) -> None:
    """http_api's PATCH endpoints: runtime settings + one event each."""
    runtime_settings.set_approval_mode("s1", session, approval_mode)
    setting_events.persist_approval_mode("s1", approval_mode)
    runtime_settings.set_profile("s1", session, profile)
    setting_events.persist_profile("s1", profile)


def _build_session(monkeypatch, *, running: bool = False):
    log = install(monkeypatch)
    s = Session(session_id="s1", initial_cwd="/w", startup_tool_calls=[{"name": "x"}])
    create(s)

    # t1: tool step + summary, then answer.
    st1 = subturn("st1", "q1")
    t1 = start_turn(s, "t1", st1)
    set_title(s, t1, "T1")
    step(s, st1, _tool_step("c1"))
    st1.detailed_summary = "notes 1"
    end_turn(s, t1, st1, _final("a1"))

    # t2 with a follow-up (reopened, completed again).
    st2 = subturn("st2", "q2")
    t2 = start_turn(s, "t2", st2)
    set_title(s, t2, "T2")
    end_turn(s, t2, st2, _final("a2"))
    st3 = subturn("st3", "follow-up")
    start_turn(s, "t2", st3, follow_up=True)
    set_title(s, t2, "T2 revised")
    end_turn(s, t2, st3, _final("a3"))

    # t3 cancelled after a tool step; settings change in between.
    _change_settings(s, "full-auto", "p2")
    st4 = subturn("st4", "q3")
    t3 = start_turn(s, "t3", st4)
    step(s, st4, _tool_step("c2"))
    end_turn(s, t3, st4, _final("[Action Cancelled by User]"), cancelled=True)

    # t4, t5 plain; t5 leaves a todo list behind.
    for tid, sid in (("t4", "st5"), ("t5", "st6")):
        st = subturn(sid, f"q-{tid}")
        turn = start_turn(s, tid, st)
        set_title(s, turn, tid.upper())
        if tid == "t5":
            s.session_data["todo_list"] = [{"text": "a", "status": "open"}]
        end_turn(s, turn, st, _final(f"a-{tid}"))

    if running:
        st7 = subturn("st7", "q6")
        start_turn(s, "t6", st7)
        step(s, st7, _tool_step("c3"))
    s.startup_done = True
    session_writes.write_startup_done("s1", s)
    return s, log


def _all_turns(session: Session) -> list[Turn]:
    turns = list(session.completed_turns)
    if session.current_turn is not None:
        turns.append(session.current_turn)
    return turns


def _readers(session: Session) -> dict:
    """Everything that reads past turns, for a new message in a new turn."""
    new_turn = Turn(id="new", subturns=[subturn("stN", "next question")])
    return {
        "payload": _build_llm_payload(session, new_turn),
        "skills": _build_skill_selector_transcript(session, new_turn),
        "title": _build_title_context(session, new_turn),
        "meta": derive_meta(session),
        "last_final": final_answer(session.completed_turns[-1].subturns[-1]),
    }


@pytest.mark.parametrize("running", [False, True])
def test_cache_built_session_reads_exactly_like_full_replay(
    monkeypatch, running
) -> None:
    session, log = _build_session(monkeypatch, running=running)
    wire_cache_db(monkeypatch, log)
    full = replay_events("s1", log.rows)
    cached = session_db_load._session_from_cache("s1")

    assert cached is not None
    assert [t.from_cache for t in _all_turns(cached)][-2:] == [False, False]
    assert any(t.from_cache for t in _all_turns(cached))
    assert _readers(cached) == _readers(full)
    # The last two turns are complete copies, and session-level state matches.
    assert [turn_to_dict(t) for t in _all_turns(cached)[-2:]] == [
        turn_to_dict(t) for t in _all_turns(full)[-2:]
    ]
    for field in ("approval_mode", "profile_name", "startup_done", "initial_cwd"):
        assert getattr(cached, field) == getattr(full, field)
    assert cached.session_data["todo_list"] == full.session_data["todo_list"]


def test_cache_gap_falls_back_to_full_replay(monkeypatch) -> None:
    _, log = _build_session(monkeypatch)
    del log.cache[(1, 1)]
    del log.index[1]
    wire_cache_db(monkeypatch, log)
    assert session_db_load._session_from_cache("s1") is None


@pytest.mark.parametrize("running", [False, True])
def test_live_write_rows_match_backfill_rows(monkeypatch, running) -> None:
    session, log = _build_session(monkeypatch, running=running)
    full = replay_events("s1", log.rows)
    starts = log.starts()
    index: list[dict] = []
    cache: list[dict] = []
    for seq, turn in enumerate(_all_turns(full), 1):
        turn_row, subturn_rows = project_turn(turn, seq, starts[turn.id])
        index.append(turn_row)
        cache.extend(subturn_rows)

    assert [log.index[k] for k in sorted(log.index)] == index
    assert [log.cache[k] for k in sorted(log.cache)] == cache


def _record_writes(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        session_writes,
        "persist_save",
        lambda sid, events, turns, subturns, meta: calls.append(
            (events, turns, subturns)
        ),
    )
    return calls


def test_writes_on_a_cache_built_session_match_a_full_replay(monkeypatch) -> None:
    session, log = _build_session(monkeypatch)
    wire_cache_db(monkeypatch, log)
    written = []
    for loaded in (
        session_db_load._session_from_cache("s1"),
        replay_events("s1", log.rows),
    ):
        calls = _record_writes(monkeypatch)
        # A follow-up reopening the last turn, then a new turn.
        st = subturn("st8", "more")
        turn = start_turn(loaded, "t5", st, follow_up=True)
        step(loaded, st, _tool_step("c8"))
        end_turn(loaded, turn, st, _final("a8"))
        st = subturn("st9", "q9")
        turn = start_turn(loaded, "t9", st)
        end_turn(loaded, turn, st, _final("a9"))
        written.append(calls)

    assert written[0] == written[1]
    types = [t for events, _, _ in written[0] for t, _ in events]
    assert types == [
        "turn_reopened",
        "subturn_started",
        "exchange_recorded",
        "exchange_recorded",
        "turn_completed",
        "turn_started",
        "subturn_started",
        "todo_list_set",
        "exchange_recorded",
        "turn_completed",
    ]


def test_writing_a_stub_turn_is_refused() -> None:
    session = Session(session_id="s1")
    session.completed_turns = [
        stub_turn_from_cache(
            {"turn_id": "t1", "title": None, "completed": True},
            [{"subturn_id": "st1", "final_response": "a"}],
        )
    ]
    with pytest.raises(RuntimeError, match="chat history cache"):
        cache_rows_for_save(session, [("exchange_recorded", {"subturn_id": "st1"})])


def test_replay_ignores_repeated_copies_of_sealed_turns(monkeypatch) -> None:
    """The pre-fix save path could re-write every turn (see list_turn_starts)."""
    session, log = _build_session(monkeypatch)
    wire_cache_db(monkeypatch, log)
    expected = session_db_load._session_from_cache("s1")
    copy = [dict(r, id=len(log.rows) + i + 1) for i, r in enumerate(list(log.rows))]
    log.rows.extend(copy)

    again = session_db_load._session_from_cache("s1")
    assert [turn_to_dict(t) for t in _all_turns(again)] == [
        turn_to_dict(t) for t in _all_turns(expected)
    ]


def test_stub_keeps_the_closed_subturn_fields() -> None:
    turn = Turn(
        id="t1",
        subturns=[subturn("st1", "q1")],
        task_title="T",
        completed=True,
    )
    turn.subturns[0].exchanges += [_tool_step("c1"), _final("answer")]
    turn.subturns[0].detailed_summary = "notes"
    turn_row, subturn_rows = project_turn(turn, 1, 10)
    stub = stub_turn_from_cache(turn_row, subturn_rows)

    assert subturn_rows[0]["final_response"] == "answer"
    assert stub.from_cache and stub.completed and stub.task_title == "T"
    assert final_answer(stub.subturns[0]) == "answer"
    assert stub.subturns[0].detailed_summary == "notes"
    assert stub.subturns[0].user_text_with_context == "[ctx] q1"


# ---------------------------------------------------------------------------
# Settings changes
# ---------------------------------------------------------------------------


def test_settings_change_is_one_event_and_turn_writes_never_repeat_it(
    monkeypatch,
) -> None:
    session, log = _build_session(monkeypatch)
    before = len(log.rows)

    setting_events.persist_approval_mode("s1", "default")
    setting_events.persist_profile("s1", "p3")
    heartbeat = {"enabled": True, "interval_minutes": 30}
    setting_events.persist_heartbeat_settings("s1", heartbeat)
    runtime_settings.set_approval_mode("s1", session, "default")
    runtime_settings.set_profile("s1", session, "p3")
    runtime_settings.set_heartbeat_settings("s1", session, heartbeat)
    st = subturn("st9", "q9")
    turn = start_turn(session, "t9", st)
    end_turn(session, turn, st, _final("a9"))

    assert log.types()[before:] == [
        "approval_mode_set",
        "profile_set",
        "heartbeat_settings_set",
        "turn_started",
        "subturn_started",
        "todo_list_set",
        "exchange_recorded",
        "turn_completed",
    ]
    assert log.setting_meta[-1] == {"heartbeat_enabled": 1}
    # The turn's writes carry the new settings in session_meta.
    assert log.meta["profile_name"] == "p3"


def test_session_level_types_cover_every_settings_event() -> None:
    assert {"approval_mode_set", "profile_set", "heartbeat_settings_set"} <= set(
        SESSION_LEVEL_EVENT_TYPES
    )


# ---------------------------------------------------------------------------
# Backfill and CLI
# ---------------------------------------------------------------------------


def _wire_backfill(monkeypatch, log: EventLog, replaced: list) -> None:
    monkeypatch.setattr(
        session_cache_backfill,
        "load_session_meta",
        lambda sid: {"schema_version": 6},
    )
    monkeypatch.setattr(
        session_cache_backfill, "max_event_id", lambda sid: log.rows[-1]["id"]
    )
    monkeypatch.setattr(
        session_cache_backfill,
        "load_event_page",
        lambda sid, after, upto, limit: [
            r for r in log.rows if after < r["id"] <= upto
        ][:limit],
    )
    monkeypatch.setattr(
        session_cache_backfill,
        "replace_session_cache",
        lambda sid, turns, subturns: replaced.append((turns, subturns)),
    )


def test_backfill_writes_the_live_save_rows(monkeypatch) -> None:
    _, log = _build_session(monkeypatch, running=True)
    replaced: list = []
    _wire_backfill(monkeypatch, log, replaced)

    result = session_cache_backfill.fill_session_cache("s1")

    assert result.skipped is None
    assert result.turns == 6
    assert replaced == [
        (
            [log.index[k] for k in sorted(log.index)],
            [log.cache[k] for k in sorted(log.cache)],
        )
    ]


def test_backfill_dry_run_writes_nothing(monkeypatch) -> None:
    _, log = _build_session(monkeypatch)
    replaced: list = []
    _wire_backfill(monkeypatch, log, replaced)
    result = session_cache_backfill.fill_session_cache("s1", dry_run=True)
    assert result.turns == 5 and replaced == []


def test_backfill_failure_propagates(monkeypatch) -> None:
    _, log = _build_session(monkeypatch)
    _wire_backfill(monkeypatch, log, [])

    def boom(*args):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(session_cache_backfill, "replace_session_cache", boom)
    with pytest.raises(RuntimeError, match="insert failed"):
        session_cache_backfill.fill_session_cache("s1")


def test_cli_refuses_to_run_while_the_server_is_up(monkeypatch) -> None:
    class _Proc:
        pid = 123
        role = "flask"

    import src.utils.process_doctor as process_doctor

    monkeypatch.setattr(process_doctor, "find_slbp_processes", lambda: [_Proc()])
    ran: list = []
    monkeypatch.setitem(
        intense_migration._MIGRATIONS,
        "fill-session-cache",
        (lambda dry_run, sid: ran.append(dry_run), ""),
    )
    runner = CliRunner()

    result = runner.invoke(
        intense_migration.intense_migration, ["run", "fill-session-cache"]
    )
    assert result.exit_code == 1 and ran == []
    assert "Stop it first" in result.output

    # A dry run only reads, so it may run while the server is up.
    result = runner.invoke(
        intense_migration.intense_migration,
        ["run", "fill-session-cache", "--dry-run"],
    )
    assert result.exit_code == 0 and ran == [True]
