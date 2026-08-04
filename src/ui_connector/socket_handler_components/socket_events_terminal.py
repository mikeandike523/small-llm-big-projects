from __future__ import annotations

import logging
import os
import threading

from flask import request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.terminal import (
    _terminal_belongs_to_session,
    _new_terminal_id,
    _next_human_terminal_name,
    _format_cmd_display,
    _get_terminal_meta,
    _terminal_output_pump,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Terminal socket event handlers
# ---------------------------------------------------------------------------


@socketio.on("terminal_create")
def handle_terminal_create(data: dict):
    data = data or {}
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return

    cwd = _state._session_current_cwd.get(session_id) or os.getcwd() or None
    terminal_id = _new_terminal_id()
    name = str(data.get("name") or _next_human_terminal_name(session_id))
    try:
        session = _state._terminal_manager.create(
            name=name, cwd=cwd, rows=24, cols=80, terminal_id=terminal_id
        )
        _state._terminal_session_rooms[session.id] = session_id
    except Exception as exc:
        _state._terminal_session_rooms.pop(terminal_id, None)
        logger.warning("Failed to create terminal for session %s: %s", session_id, exc)
        socketio.emit(
            "error", {"message": f"Failed to create terminal: {exc}"}, room=session_id
        )
        return

    _state._terminal_opened_by[session.id] = "user"
    meta = _get_terminal_meta(session_id)
    meta["user_last_opened"] = session.id
    t = threading.Thread(
        target=_terminal_output_pump,
        args=(session_id, session, session.process),
        daemon=True,
    )
    _state._terminal_output_threads[session.id] = t
    socketio.emit(
        "terminal_created",
        {
            "terminal_id": session.id,
            "name": session.name,
            "cmd_display": _format_cmd_display(session.cmd),
        },
        room=session_id,
    )
    t.start()


@socketio.on("terminal_input")
def handle_terminal_input(data: dict):
    data = data or {}
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return

    terminal_id = str(data.get("terminal_id") or "")
    if not _terminal_belongs_to_session(session_id, terminal_id):
        return

    raw = str(data.get("data") or "")
    session = _state._terminal_manager.get(terminal_id)
    if session and session.process.is_alive():
        session.process.write(raw.encode("utf-8", errors="replace"))


@socketio.on("terminal_resize")
def handle_terminal_resize(data: dict):
    data = data or {}
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return

    terminal_id = str(data.get("terminal_id") or "")
    if not _terminal_belongs_to_session(session_id, terminal_id):
        return

    try:
        rows = max(1, int(data.get("rows", 24)))
        cols = max(1, int(data.get("cols", 80)))
    except (TypeError, ValueError):
        rows, cols = 24, 80

    session = _state._terminal_manager.get(terminal_id)
    if session and session.process.is_alive():
        session.process.resize(rows, cols)
        session.resize_screen(rows, cols)


@socketio.on("terminal_close")
def handle_terminal_close(data: dict):
    data = data or {}
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return

    terminal_id = str(data.get("terminal_id") or "")
    if not _terminal_belongs_to_session(session_id, terminal_id):
        return

    _state._terminal_session_rooms.pop(terminal_id, None)
    _state._terminal_opened_by.pop(terminal_id, None)
    _state._terminal_manager.destroy(terminal_id)


@socketio.on("terminal_tab_focused")
def handle_terminal_tab_focused(data: dict):
    data = data or {}
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return
    terminal_id = str(data.get("terminal_id") or "")
    if not _terminal_belongs_to_session(session_id, terminal_id):
        return
    _get_terminal_meta(session_id)["active"] = terminal_id


@socketio.on("terminal_ask_about")
def handle_terminal_ask_about(data: dict):
    data = data or {}
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return
    terminal_id = str(data.get("terminal_id") or "")
    if not _terminal_belongs_to_session(session_id, terminal_id):
        return
    _get_terminal_meta(session_id)["last_asked"] = terminal_id
