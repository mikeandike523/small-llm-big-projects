"""Chat history cache (migration v18): cache-built sessions match full replay.

A session loaded from `chat_turn_index` / `chat_history_cache` (sealed turns
as stubs, the last two turns replayed from events) must give every reader of
the conversation exactly what a full event-log replay gives, and saving it must
never write the stubs back. The live save path and the backfill must produce
identical cache rows.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.cli_routes import intense_migration
from src.ui_connector.socket_handler_components import (
    session_db_load,
    setting_events,
)
from src.ui_connector.socket_handler_components._session_event_emit import (
    build_cursor,
    cache_rows_for_save,
    compute_events,
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
    subturn_final_response,
)
from src.utils.session_events import (
    SESSION_LEVEL_EVENT_TYPES,
    derive_meta,
    replay_events,
)
from src.utils.session_model import (
    LLMExchange,
    Session,
    Subturn,
    ToolCallRecord,
    Turn,
    turn_to_dict,
)


class _EventLog:
    """session_events plus the cache rows the live save path would write."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.cursor: dict = {}
        self.index: dict[int, dict] = {}
        self.cache: dict[tuple[int, int], dict] = {}

    def save(self, session: Session) -> list[str]:
        events = compute_events(session, self.cursor)
        starts: dict[str, int] = {}
        for event_type, payload in events:
            row_id = len(self.rows) + 1
            self.rows.append(
                {
                    "id": row_id,
                    "event_type": event_type,
                    "payload": json.loads(json.dumps(payload)),
                }
            )
            if event_type == "turn_started":
                starts[payload["turn_id"]] = row_id
        turn_rows, subturn_rows = cache_rows_for_save(session, events)
        for row in turn_rows:
            # Same rule as chat_history_cache_db._execute_upsert_turn_rows.
            start = starts.get(row["turn_id"])
            if start is not None:
                self.index[row["turn_seq"]] = {**row, "start_event_id": start}
            else:
                existing = self.index[row["turn_seq"]]
                assert existing["turn_id"] == row["turn_id"]
                existing.update(title=row["title"], completed=row["completed"])
        for row in subturn_rows:
            self.cache[(row["turn_seq"], row["subturn_seq"])] = row
        return [event_type for event_type, _ in events]

    def starts(self) -> dict[str, int]:
        return {
            row["payload"]["turn_id"]: row["id"]
            for row in self.rows
            if row["event_type"] == "turn_started"
        }


def _st(sid: str, text: str) -> Subturn:
    return Subturn(id=sid, user_text=text, user_text_with_context=f"[ctx] {text}")


def _final(text: str) -> LLMExchange:
    return LLMExchange(assistant_content=text, is_final=True)


def _tool_step(call_id: str) -> LLMExchange:
    return LLMExchange(
        assistant_content="looking",
        tool_calls=[ToolCallRecord(id=call_id, name="t", args={}, result="big output")],
    )


def _complete(session: Session, turn: Turn) -> None:
    turn.completed = True
    session.completed_turns.append(turn)
    session.current_turn = None


def _build_session(*, running: bool = False) -> tuple[Session, _EventLog]:
    s = Session(session_id="s1", initial_cwd="/w", startup_tool_calls=[{"name": "x"}])
    log = _EventLog()
    log.save(s)

    # t1: tool step + summary, then answer.
    t1 = Turn(id="t1", subturns=[_st("st1", "q1")], task_title="T1")
    s.current_turn = t1
    log.save(s)
    t1.subturns[0].exchanges += [_tool_step("c1"), _final("a1")]
    t1.subturns[0].detailed_summary = "notes 1"
    s.session_data["todo_list"] = [{"text": "a", "status": "open"}]
    _complete(s, t1)
    log.save(s)

    # t2 with a follow-up (reopened, completed again).
    t2 = Turn(id="t2", subturns=[_st("st2", "q2")], task_title="T2")
    s.current_turn = t2
    t2.subturns[0].exchanges.append(_final("a2"))
    _complete(s, t2)
    log.save(s)
    s.completed_turns.pop()
    t2.completed = False
    t2.subturns.append(_st("st3", "follow-up"))
    s.current_turn = t2
    log.save(s)
    t2.subturns[1].exchanges.append(_final("a3"))
    t2.task_title = "T2 revised"
    _complete(s, t2)
    log.save(s)

    # t3 cancelled with only a tool step; settings change in between.
    s.approval_mode = "full-auto"
    s.profile_name = "p2"
    t3 = Turn(id="t3", subturns=[_st("st4", "q3")])
    s.current_turn = t3
    t3.subturns[0].exchanges.append(_tool_step("c2"))
    t3.was_cancelled = True
    _complete(s, t3)
    log.save(s)

    # t4, t5 plain.
    for tid, sid in (("t4", "st5"), ("t5", "st6")):
        turn = Turn(id=tid, subturns=[_st(sid, f"q-{tid}")], task_title=tid.upper())
        s.current_turn = turn
        turn.subturns[0].exchanges.append(_final(f"a-{tid}"))
        _complete(s, turn)
        log.save(s)

    if running:
        t6 = Turn(id="t6", subturns=[_st("st7", "q6")])
        s.current_turn = t6
        t6.subturns[0].exchanges.append(_tool_step("c3"))
        log.save(s)
    s.startup_done = True
    log.save(s)
    return s, log


def _wire_cache_db(monkeypatch, log: _EventLog) -> None:
    """Point session_db_load's cache path at the in-memory log and cache."""
    index = [log.index[k] for k in sorted(log.index)]

    def last_turn_rows(session_id, count):
        return index[-count:]

    def cached_history(session_id, below):
        return [
            (
                row,
                [log.cache[k] for k in sorted(log.cache) if k[0] == row["turn_seq"]],
            )
            for row in index
            if row["turn_seq"] < below
        ]

    def latest_rows(session_id, types, *, upto_id=None):
        found = {}
        for row in log.rows:
            if row["event_type"] in types and (upto_id is None or row["id"] <= upto_id):
                found[row["event_type"]] = row
        return sorted(found.values(), key=lambda r: r["id"])

    def page(session_id, after, upto, limit):
        return [r for r in log.rows if after < r["id"] <= upto][:limit]

    monkeypatch.setattr(session_db_load, "load_last_turn_rows", last_turn_rows)
    monkeypatch.setattr(session_db_load, "load_cached_history", cached_history)
    monkeypatch.setattr(session_db_load, "load_latest_event_rows", latest_rows)
    monkeypatch.setattr(session_db_load, "load_event_page", page)
    monkeypatch.setattr(session_db_load, "max_event_id", lambda sid: log.rows[-1]["id"])


def _all_turns(session: Session) -> list[Turn]:
    turns = list(session.completed_turns)
    if session.current_turn is not None:
        turns.append(session.current_turn)
    return turns


def _readers(session: Session) -> dict:
    """Everything that reads past turns, for a new message in a new turn."""
    new_turn = Turn(id="new", subturns=[_st("stN", "next question")])
    return {
        "payload": _build_llm_payload(session, new_turn),
        "skills": _build_skill_selector_transcript(session, new_turn),
        "title": _build_title_context(session, new_turn),
        "meta": derive_meta(session),
        "last_final": subturn_final_response(session.completed_turns[-1].subturns[-1]),
    }


@pytest.mark.parametrize("running", [False, True])
def test_cache_built_session_reads_exactly_like_full_replay(
    monkeypatch, running
) -> None:
    session, log = _build_session(running=running)
    _wire_cache_db(monkeypatch, log)
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
    _, log = _build_session()
    del log.cache[(1, 1)]
    del log.index[1]
    _wire_cache_db(monkeypatch, log)
    assert session_db_load._session_from_cache("s1") is None


@pytest.mark.parametrize("running", [False, True])
def test_live_save_rows_match_backfill_rows(running) -> None:
    session, log = _build_session(running=running)
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


def test_saving_a_cache_built_session_emits_only_new_events(monkeypatch) -> None:
    session, log = _build_session()
    _wire_cache_db(monkeypatch, log)
    full = replay_events("s1", log.rows)
    cached = session_db_load._session_from_cache("s1")
    cursor = build_cursor(cached)
    assert compute_events(cached, dict(cursor)) == []

    # The same new turn on both copies produces the same events and rows.
    full_cursor = build_cursor(full)
    for s, c in ((cached, cursor), (full, full_cursor)):
        s.current_turn = Turn(id="t9", subturns=[_st("st9", "q9")])
    assert compute_events(cached, cursor) == compute_events(full, full_cursor)
    # The cursor only remembers the last two turns.
    assert set(cursor["turns"]) == {"t5", "t9"}


def test_a_stub_in_the_save_window_is_refused() -> None:
    session = Session(session_id="s1")
    session.completed_turns = [
        stub_turn_from_cache(
            {"turn_id": "t1", "title": None, "completed": True},
            [{"subturn_id": "st1", "final_response": "a"}],
        )
    ]
    with pytest.raises(RuntimeError, match="chat history cache"):
        compute_events(session, {})


def test_stub_keeps_the_closed_subturn_fields() -> None:
    turn = Turn(
        id="t1",
        subturns=[_st("st1", "q1")],
        task_title="T",
        completed=True,
    )
    turn.subturns[0].exchanges += [_tool_step("c1"), _final("answer")]
    turn.subturns[0].detailed_summary = "notes"
    turn_row, subturn_rows = project_turn(turn, 1, 10)
    stub = stub_turn_from_cache(turn_row, subturn_rows)

    assert subturn_rows[0]["final_response"] == "answer"
    assert stub.from_cache and stub.completed and stub.task_title == "T"
    assert subturn_final_response(stub.subturns[0]) == "answer"
    assert stub.subturns[0].detailed_summary == "notes"
    assert stub.subturns[0].user_text_with_context == "[ctx] q1"


# ---------------------------------------------------------------------------
# Settings changes
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value


def test_settings_change_appends_once_and_the_next_save_adds_nothing(
    monkeypatch,
) -> None:
    session, log = _build_session()
    r = _FakeRedis()
    r.setex("session:s1:persist_state", 0, json.dumps(log.cursor))
    appended: list = []
    monkeypatch.setattr(setting_events._state, "_get_redis", lambda: r)
    monkeypatch.setattr(
        setting_events,
        "append_setting_event",
        lambda sid, event_type, payload, meta: appended.append(
            (event_type, payload, meta)
        ),
    )

    setting_events.persist_approval_mode("s1", "default")
    setting_events.persist_profile("s1", "p3")
    heartbeat = {"enabled": True, "interval_minutes": 30}
    setting_events.persist_heartbeat_settings("s1", heartbeat)

    assert [a[0] for a in appended] == [
        "approval_mode_set",
        "profile_set",
        "heartbeat_settings_set",
    ]
    assert appended[2][2] == {"heartbeat_enabled": 1}
    # The agent's Session copy picks the new values up from runtime_settings
    # before saving; with the updated cursor that save writes nothing new.
    session.approval_mode = "default"
    session.profile_name = "p3"
    session.session_data["heartbeat_settings"] = heartbeat
    cursor = json.loads(r.values["session:s1:persist_state"])
    assert compute_events(session, cursor) == []


def test_session_level_types_cover_every_settings_event() -> None:
    assert {"approval_mode_set", "profile_set", "heartbeat_settings_set"} <= set(
        SESSION_LEVEL_EVENT_TYPES
    )


# ---------------------------------------------------------------------------
# Backfill and CLI
# ---------------------------------------------------------------------------


def _wire_backfill(monkeypatch, log: _EventLog, replaced: list) -> None:
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
    _, log = _build_session(running=True)
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
    _, log = _build_session()
    replaced: list = []
    _wire_backfill(monkeypatch, log, replaced)
    result = session_cache_backfill.fill_session_cache("s1", dry_run=True)
    assert result.turns == 5 and replaced == []


def test_backfill_failure_propagates(monkeypatch) -> None:
    _, log = _build_session()
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
