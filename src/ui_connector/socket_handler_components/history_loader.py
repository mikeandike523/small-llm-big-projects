"""Progressive session history loading.

The client sends `begin_history_load {loadId}` once `session_state` arrives.
A dedicated worker thread then streams the session to that one browser
connection (never the session room):

  history_load_started {loadId, turnIds, running}
  history_turn_bundle  {loadId, seq, turn}     one finished turn, oldest first
  history_load_done    {loadId, events, liveTodoItems, error?}

Turns are assembled from MySQL `session_events` page by page
(`TurnBundleAssembler`), so no code serializes the whole conversation. A
consistent snapshot is taken up front under the session's persistence lock:
the MySQL cutoff (`MAX(id)`), plus the Redis log's not-yet-saved events after
the agent loop's bookmark. MySQL up to the cutoff + those events = everything
that happened before the snapshot; anything later reaches the client as live
socket events, which it holds until `history_load_done`.

Bundles are sent with acknowledgements and at most `_MAX_UNACKED` in flight,
so the browser renders one turn at a time and a slow client isn't flooded.
"""

from __future__ import annotations

import logging
import threading
import uuid

from flask import request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components import runtime_settings
from src.tools.todo_list import format_items_for_ui
from src.utils.event_log import get_events_since, get_watermark
from src.utils.session_history_bundles import TurnBundleAssembler
from src.utils.session_model import CURRENT_SCHEMA_VERSION
from src.utils.session_schema_repair import repair_event_log
from src.utils.sql.session_store_db import (
    list_turn_starts,
    load_event_page,
    load_session_meta,
    load_thinking_char_counts,
    max_event_id,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 200
_MAX_UNACKED = 2
_ACK_POLL_SECONDS = 0.5

# sid -> (load_id, cancel event) for the connection's in-flight load.
_loads: dict[str, tuple[str, threading.Event]] = {}
_loads_lock = threading.Lock()


class _LoadCancelled(Exception):
    pass


@socketio.on("begin_history_load")
def handle_begin_history_load(data: dict | None = None):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return
    load_id = str((data or {}).get("loadId") or uuid.uuid4())
    cancel = threading.Event()
    with _loads_lock:
        previous = _loads.get(sid)
        if previous is not None:
            previous[1].set()
        _loads[sid] = (load_id, cancel)
    threading.Thread(
        target=_run_history_load,
        args=(sid, session_id, load_id, cancel),
        name=f"history-loader-{uuid.uuid4()}",
        daemon=True,
    ).start()


def cancel_history_load(sid: str) -> None:
    """Stop the connection's in-flight load (called on disconnect)."""
    with _loads_lock:
        entry = _loads.pop(sid, None)
    if entry is not None:
        entry[1].set()


def _run_history_load(
    sid: str, session_id: str, load_id: str, cancel: threading.Event
) -> None:
    try:
        _stream_history(sid, session_id, load_id, cancel)
    except _LoadCancelled:
        logger.info("History load %s for session %s cancelled", load_id, session_id)
    except Exception as exc:
        logger.exception("History load failed for session %s", session_id)
        socketio.emit(
            "history_load_done",
            {
                "loadId": load_id,
                "events": [],
                "liveTodoItems": None,
                "error": f"Could not load session history: {exc}",
            },
            to=sid,
        )
    finally:
        with _loads_lock:
            if _loads.get(sid, (None,))[0] == load_id:
                _loads.pop(sid, None)


def _stream_history(
    sid: str, session_id: str, load_id: str, cancel: threading.Event
) -> None:
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

    turn_starts = [s for s in list_turn_starts(session_id) if s[0] <= cutoff]
    socketio.emit(
        "history_load_started",
        {
            "loadId": load_id,
            "turnIds": [turn_id for _, turn_id in turn_starts],
            "running": running,
        },
        to=sid,
    )

    thinking_counts = load_thinking_char_counts(session_id)
    assembler = TurnBundleAssembler(session_id, turn_starts)
    window = threading.Semaphore(_MAX_UNACKED)
    seq = 0
    for row in _iter_rows(session_id, cutoff, cancel):
        for turn in assembler.feed(row):
            _attach_thinking_chars(turn, thinking_counts)
            _send_bundle(sid, load_id, seq, turn, window, cancel)
            seq += 1
    for turn in assembler.finish():
        _attach_thinking_chars(turn, thinking_counts)
        _send_bundle(sid, load_id, seq, turn, window, cancel)
        seq += 1

    socketio.emit(
        "history_load_done",
        {
            "loadId": load_id,
            "events": unsaved,
            "liveTodoItems": (
                format_items_for_ui(assembler.todo_list) if running else None
            ),
        },
        to=sid,
    )


def _attach_thinking_chars(turn: dict, counts: dict[str, tuple[int, int]]) -> None:
    """Add each subturn's saved thinking character counts (display metadata)."""
    for st in turn.get("subturns", []):
        native, irat = counts.get(st.get("id"), (0, 0))
        st["native_thinking_chars"] = native
        st["irat_thinking_chars"] = irat


def _iter_rows(session_id: str, cutoff: int, cancel: threading.Event):
    """Yield event rows up to `cutoff` in id order, page by page."""
    meta = load_session_meta(session_id) or {}
    if meta.get("schema_version", CURRENT_SCHEMA_VERSION) != CURRENT_SCHEMA_VERSION:
        # An old-schema session must be repaired as a whole before replay
        # (resume_session already flagged it if no repair chain exists).
        # Repairers copy rows, so each keeps its real `id`.
        rows = load_event_page(session_id, 0, cutoff, 2**62)
        repaired = repair_event_log(meta, rows, CURRENT_SCHEMA_VERSION)
        if repaired is not None:
            yield from repaired[1]
        return
    after = 0
    while True:
        if cancel.is_set():
            raise _LoadCancelled()
        page = load_event_page(session_id, after, cutoff, _PAGE_SIZE)
        if not page:
            return
        yield from page
        after = page[-1]["id"]


def _send_bundle(
    sid: str,
    load_id: str,
    seq: int,
    turn: dict,
    window: threading.Semaphore,
    cancel: threading.Event,
) -> None:
    while not window.acquire(timeout=_ACK_POLL_SECONDS):
        if cancel.is_set():
            raise _LoadCancelled()
    if cancel.is_set():
        raise _LoadCancelled()
    socketio.emit(
        "history_turn_bundle",
        {"loadId": load_id, "seq": seq, "turn": turn},
        to=sid,
        callback=lambda *_: window.release(),
    )
