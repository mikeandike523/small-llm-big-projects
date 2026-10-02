"""Session history, loaded one turn at a time on request.

The session page shows one turn per page, so the browser asks for turns as it
needs them with a single acknowledged socket call:

  load_turn {latest: true}
      -> {turnIds, turn, running, events, liveTodoItems}
  load_turn {turnId}
      -> {turnId, turn}
  (either may instead return {error})

A turn is assembled from MySQL `session_events` by its own id range: every turn
has exactly one `turn_started` event, so turn N's events lie in
[start_N, start_N+1). No code serializes the whole conversation.

The latest-turn load also takes a consistent snapshot under the session's
persistence lock: the MySQL cutoff (`MAX(id)`), plus the Redis log's
not-yet-saved events after the agent loop's bookmark. MySQL up to the cutoff
+ those events = everything that happened before the snapshot; anything later
reaches the client as live socket events, which it holds until this load
returns.
"""

from __future__ import annotations

import logging

from flask import request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components import runtime_settings
from src.tools.todo_list import format_items_for_ui
from src.utils.event_log import get_events_since, get_watermark
from src.utils.session_events import EVT_TODO_LIST_SET
from src.utils.session_history_bundles import TurnBundleAssembler
from src.utils.session_model import CURRENT_SCHEMA_VERSION
from src.utils.session_schema_repair import repair_event_log
from src.utils.sql.session_store_db import (
    list_turn_starts,
    load_event_page,
    load_latest_event_payload,
    load_session_meta,
    load_thinking_char_counts,
    max_event_id,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 500


@socketio.on("load_turn")
def handle_load_turn(data: dict | None = None) -> dict:
    session_id = _state._sid_to_session_id.get(request.sid)
    if not session_id:
        return {"error": "This connection has no session."}
    data = data or {}
    try:
        if data.get("latest"):
            return load_latest_turn(session_id)
        turn_id = data.get("turnId")
        if not isinstance(turn_id, str) or not turn_id:
            return {"error": "load_turn needs a turnId or latest=true."}
        return load_turn(session_id, turn_id)
    except Exception as exc:
        logger.exception("Turn load failed for session %s", session_id)
        return {"error": f"Could not load session history: {exc}"}


def load_turn(session_id: str, turn_id: str) -> dict:
    """Return one turn of the session by id."""
    starts = list_turn_starts(session_id)
    index = next((i for i, (_, tid) in enumerate(starts) if tid == turn_id), None)
    if index is None:
        return {"error": f"Turn {turn_id} was not found in this session."}
    if index + 1 < len(starts):
        end = starts[index + 1][0] - 1
    else:
        end = max_event_id(session_id)
    return {"turnId": turn_id, "turn": _assemble_turn(session_id, starts[index], end)}


def load_latest_turn(session_id: str) -> dict:
    """Return the turn list, the latest turn and the running turn's live state."""
    r = _state._get_redis()
    # Saves hold this lock, and only the agent loop's saves move the bookmark,
    # so the cutoff, bookmark and unsaved events below describe one instant.
    with runtime_settings.persistence_lock(session_id):
        cutoff = max_event_id(session_id)
        running = _state.is_turn_reserved(session_id)
        unsaved = (
            get_events_since(r, session_id, get_watermark(r, session_id))
            if running
            else []
        )

    starts = [s for s in list_turn_starts(session_id) if s[0] <= cutoff]
    turn = _assemble_turn(session_id, starts[-1], cutoff) if starts else None
    live_todo_items = None
    if running:
        # The session-level todo list as of the cutoff; newer
        # todo_list_update events in `unsaved` override it on the client.
        payload = load_latest_event_payload(
            session_id, EVT_TODO_LIST_SET, upto_id=cutoff
        )
        live_todo_items = format_items_for_ui((payload or {}).get("items") or [])
    return {
        "turnIds": [turn_id for _, turn_id in starts],
        "turn": turn,
        "running": running,
        "events": unsaved,
        "liveTodoItems": live_todo_items,
    }


def _assemble_turn(session_id: str, start: tuple[int, str], end: int) -> dict | None:
    """Fold the events in [start id, end] into that turn's dict."""
    assembler = TurnBundleAssembler(session_id, [start])
    for row in _iter_rows(session_id, start[0] - 1, end):
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
    return turn


def _iter_rows(session_id: str, after: int, upto: int):
    """Yield event rows with after < id <= upto, in id order."""
    meta = load_session_meta(session_id) or {}
    if meta.get("schema_version", CURRENT_SCHEMA_VERSION) != CURRENT_SCHEMA_VERSION:
        # An old-schema session must be repaired as a whole before replay
        # (resume_session already flagged it if no repair chain exists).
        # Repairers copy rows, so each keeps its real `id`.
        rows = load_event_page(session_id, 0, max_event_id(session_id), 2**62)
        repaired = repair_event_log(meta, rows, CURRENT_SCHEMA_VERSION)
        if repaired is not None:
            yield from (row for row in repaired[1] if after < row["id"] <= upto)
        return
    while True:
        page = load_event_page(session_id, after, upto, _PAGE_SIZE)
        if not page:
            return
        yield from page
        after = page[-1]["id"]
