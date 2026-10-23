"""Backfill for the chat history cache (`slbp intense-migration run fill-session-cache`).

Sessions created before migration v18 have `history_cache_compatible = 0`:
their `chat_turn_index` / `chat_history_cache` rows were never written, so the
backend replays their whole event log instead. This rebuilds each such
session's rows from `session_events`, using the same projection as live saves
(`session_cache_projection.project_turn`), and marks the session compatible.

Each session is its own transaction (`replace_session_cache`): partial rows are
deleted first and the flag is only set if everything succeeds, so an
interrupted run can simply be started again. The server must be stopped while
this runs, or a session could gain events between being read and being
flagged.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.session_cache_projection import project_turn
from src.utils.session_events import EVT_TURN_STARTED, ReplayState, normalize_payload
from src.utils.session_model import CURRENT_SCHEMA_VERSION
from src.utils.session_schema_repair import repair_event_log
from src.utils.sql.chat_history_cache_db import (
    list_uncached_session_ids,
    replace_session_cache,
)
from src.utils.sql.session_store_db import (
    load_event_page,
    load_session_meta,
    max_event_id,
)

_PAGE_SIZE = 500


@dataclass
class BackfillResult:
    session_id: str
    events: int = 0
    turns: int = 0
    subturns: int = 0
    skipped: str | None = None  # why the session was left uncached


def list_sessions_to_fill() -> list[str]:
    return list_uncached_session_ids()


def _event_rows(session_id: str, meta: dict):
    """The session's event rows in id order, repaired to the current schema."""
    upto = max_event_id(session_id)
    if meta.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
        rows = load_event_page(session_id, 0, upto, 2**62)
        repaired = repair_event_log(meta, rows, CURRENT_SCHEMA_VERSION)
        if repaired is None:
            return None
        return iter(repaired[1])

    def pages():
        after = 0
        while True:
            page = load_event_page(session_id, after, upto, _PAGE_SIZE)
            if not page:
                return
            yield from page
            after = page[-1]["id"]

    return pages()


def fill_session_cache(session_id: str, *, dry_run: bool = False) -> BackfillResult:
    """Rebuild one session's cache rows and mark it compatible."""
    result = BackfillResult(session_id)
    meta = load_session_meta(session_id)
    if meta is None:
        result.skipped = "no session_meta row"
        return result
    rows = _event_rows(session_id, meta)
    if rows is None:
        result.skipped = f"no schema repair path from v{meta.get('schema_version')}"
        return result

    state = ReplayState(session_id)
    starts: dict[str, int] = {}
    for row in rows:
        result.events += 1
        payload = normalize_payload(row.get("payload"))
        if row.get("event_type") == EVT_TURN_STARTED and payload.get("turn_id"):
            starts.setdefault(payload["turn_id"], int(row["id"]))
        state.apply(row.get("event_type", ""), payload)
    session = state.to_session()

    turns = list(session.completed_turns)
    if session.current_turn is not None:
        turns.append(session.current_turn)
    turn_rows: list[dict] = []
    subturn_rows: list[dict] = []
    for seq, turn in enumerate(turns, 1):
        if turn.id not in starts:
            result.skipped = f"turn {turn.id} has no turn_started event"
            return result
        turn_row, rows_for_turn = project_turn(turn, seq, starts[turn.id])
        turn_rows.append(turn_row)
        subturn_rows.extend(rows_for_turn)
    result.turns = len(turn_rows)
    result.subturns = len(subturn_rows)
    if not dry_run:
        replace_session_cache(session_id, turn_rows, subturn_rows)
    return result
