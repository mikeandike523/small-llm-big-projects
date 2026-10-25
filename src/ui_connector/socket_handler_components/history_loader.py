"""Session history, loaded one turn at a time on request.

The session page shows one turn per page, so the browser asks for turns as it
needs them with a single acknowledged socket call:

  load_turn {latest: true}
      -> {turnCount, latestTurnId, turn, running, events, liveTodoItems}
  load_turn {page: N}      (1-based page = turn number)
      -> {page, turnId, turn}
  load_turn {turnId}
      -> {page, turnId, turn}
  (any may instead return {error})

A turn is assembled from MySQL `session_events` by its own id range: turn N's
events lie in [start_N, start_N+1), where start_N is its first `turn_started`
event. The range comes from `chat_turn_index` by key. Sessions whose chat
history cache is not built yet find it with the old `turn_started` scan instead
(see list_turn_starts). No code serializes the whole conversation.

The latest-turn load also takes a consistent snapshot under the session's
persistence lock: the MySQL cutoff (`MAX(id)`), plus the Redis log's
not-yet-saved events after the agent's bookmark. MySQL up to the cutoff
+ those events = everything that happened before the snapshot; anything later
reaches the client as live socket events, which it holds until this load
returns. A log without a bookmark is not replayed (see event_log.py).
"""

from __future__ import annotations

import logging

from flask import request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.session_db_load import (
    iter_event_rows,
)
from src.tools.todo_list import format_items_for_ui
from src.utils.event_log import get_events_since, get_watermark, latest_stream_id
from src.utils.session_events import EVT_TODO_LIST_SET
from src.utils.session_history_bundles import TurnBundleAssembler
from src.utils.session_model import CURRENT_SCHEMA_VERSION
from src.utils.session_schema_repair import repair_event_log
from src.utils.sql.chat_history_cache_db import (
    latest_turn_upto,
    load_history_flags,
    load_turn_rows,
    turn_seq_for_turn_id,
)
from src.utils.sql.session_store_db import (
    list_turn_starts,
    load_event_page,
    load_latest_event_payload,
    load_session_meta,
    load_thinking_char_counts,
    max_event_id,
)

logger = logging.getLogger(__name__)


@socketio.on("load_turn")
def handle_load_turn(data: dict | None = None) -> dict:
    session_id = _state._sid_to_session_id.get(request.sid)
    if not session_id:
        return {"error": "This connection has no session."}
    data = data or {}
    try:
        if data.get("latest"):
            return load_latest_turn(session_id)
        page = data.get("page")
        if isinstance(page, int) and not isinstance(page, bool):
            return load_turn_page(session_id, page)
        turn_id = data.get("turnId")
        if isinstance(turn_id, str) and turn_id:
            return load_turn_by_id(session_id, turn_id)
        return {"error": "load_turn needs latest=true, a page or a turnId."}
    except Exception as exc:
        logger.exception("Turn load failed for session %s", session_id)
        return {"error": f"Could not load session history: {exc}"}


def _cached(session_id: str) -> tuple[bool, int]:
    """(cache usable, schema_version) for the session."""
    flags = load_history_flags(session_id) or {}
    schema = flags.get("schema_version", CURRENT_SCHEMA_VERSION)
    return (
        bool(flags.get("history_cache_compatible"))
        and schema == CURRENT_SCHEMA_VERSION,
        schema,
    )


def load_turn_page(session_id: str, page: int) -> dict:
    """Return the turn on 1-based page `page`."""
    cached, schema = _cached(session_id)
    if cached:
        rows = load_turn_rows(session_id, page, page + 1)
        if not rows or rows[0]["turn_seq"] != page:
            return {"error": f"Page {page} was not found in this session."}
        start = (rows[0]["start_event_id"], rows[0]["turn_id"])
        is_latest = len(rows) == 1
        end = (
            rows[1]["start_event_id"] - 1 if not is_latest else max_event_id(session_id)
        )
    else:
        starts = list_turn_starts(session_id)
        if not 1 <= page <= len(starts):
            return {"error": f"Page {page} was not found in this session."}
        start = starts[page - 1]
        is_latest = page == len(starts)
        end = starts[page][0] - 1 if not is_latest else max_event_id(session_id)
    running = is_latest and _state.is_turn_reserved(session_id)
    return {
        "page": page,
        "turnId": start[1],
        "turn": _assemble_turn(session_id, start, end, schema, running=running),
    }


def load_turn_by_id(session_id: str, turn_id: str) -> dict:
    """Return one turn of the session by id."""
    cached, _ = _cached(session_id)
    if cached:
        page = turn_seq_for_turn_id(session_id, turn_id)
    else:
        ids = [tid for _, tid in list_turn_starts(session_id)]
        page = ids.index(turn_id) + 1 if turn_id in ids else None
    if page is None:
        return {"error": f"Turn {turn_id} was not found in this session."}
    return load_turn_page(session_id, page)


def load_latest_turn(session_id: str) -> dict:
    """Return the turn count, the latest turn and the running turn's live state."""
    r = _state._get_redis()
    # Saves hold this lock, and only the agent loop's saves move the bookmark,
    # so the cutoff, bookmark and unsaved events below describe one instant.
    with runtime_settings.persistence_lock(session_id):
        cutoff = max_event_id(session_id)
        running = _state.is_turn_reserved(session_id)
        unsaved = _unsaved_events(r, session_id) if running else []

    cached, schema = _cached(session_id)
    if cached:
        row = latest_turn_upto(session_id, cutoff)
        count = row["turn_seq"] if row else 0
        latest = (row["start_event_id"], row["turn_id"]) if row else None
    else:
        starts = [s for s in list_turn_starts(session_id) if s[0] <= cutoff]
        count = len(starts)
        latest = starts[-1] if starts else None
    turn = (
        _assemble_turn(session_id, latest, cutoff, schema, running=running)
        if latest
        else None
    )
    live_todo_items = None
    if running:
        # The session-level todo list as of the cutoff; newer
        # todo_list_update events in `unsaved` override it on the client.
        payload = load_latest_event_payload(
            session_id, EVT_TODO_LIST_SET, upto_id=cutoff
        )
        live_todo_items = format_items_for_ui((payload or {}).get("items") or [])
    return {
        "turnCount": count,
        "latestTurnId": latest[1] if latest else None,
        "turn": turn,
        "running": running,
        "events": unsaved,
        "liveTodoItems": live_todo_items,
    }


def _unsaved_events(r, session_id: str) -> list[dict]:
    """The logged events after the bookmark, or [] if the bookmark is missing.

    Without the bookmark there is no telling which logged events MySQL already
    contains, so replaying them could show them twice. The page still shows
    everything up to the last step write, and new events arrive live.
    """
    watermark = get_watermark(r, session_id)
    if watermark is not None:
        return get_events_since(r, session_id, watermark)
    if latest_stream_id(r, session_id) is not None:
        logger.warning(
            "Session %s: the event log has no bookmark; not replaying it.",
            session_id,
        )
    return []


def _assemble_turn(
    session_id: str,
    start: tuple[int, str],
    end: int,
    schema_version: int,
    *,
    running: bool,
) -> dict | None:
    """Fold the events in [start id, end] into that turn's dict.

    Each subturn gets `interrupted`: it has no final exchange and is not the
    live subturn of a running turn (`running` = this is the latest turn and a
    turn is running). Nothing stored says so; see conversation_history.py.
    """
    assembler = TurnBundleAssembler(session_id, [start])
    for row in _iter_rows(session_id, start[0] - 1, end, schema_version):
        assembler.feed(row)
    turns = assembler.finish()
    if not turns:
        return None
    turn = turns[0]
    counts = load_thinking_char_counts(
        session_id, [st["id"] for st in turn.get("subturns", [])]
    )
    for st in turn.get("subturns", []):
        native, irat = counts.get(st.get("id"), (0, 0))
        st["native_thinking_chars"] = native
        st["irat_thinking_chars"] = irat
    subturns = turn.get("subturns", [])
    for i, st in enumerate(subturns):
        live = running and not turn.get("completed") and i == len(subturns) - 1
        st["interrupted"] = not live and not any(
            ex.get("is_final") for ex in st.get("exchanges", [])
        )
    return turn


def _iter_rows(session_id: str, after: int, upto: int, schema_version: int):
    """Yield event rows with after < id <= upto, in id order."""
    if schema_version != CURRENT_SCHEMA_VERSION:
        # An old-schema session must be repaired as a whole before replay
        # (resume_session already flagged it if no repair chain exists).
        # Repairers copy rows, so each keeps its real `id`.
        meta = load_session_meta(session_id) or {}
        rows = load_event_page(session_id, 0, max_event_id(session_id), 2**62)
        repaired = repair_event_log(meta, rows, CURRENT_SCHEMA_VERSION)
        if repaired is not None:
            yield from (row for row in repaired[1] if after < row["id"] <= upto)
        return
    yield from iter_event_rows(session_id, after, upto)
