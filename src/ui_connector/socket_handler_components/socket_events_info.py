from __future__ import annotations

import os

from flask import request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.session_store import (
    _load_session,
    _get_session_system_prompt,
    _get_skills_info_payload,
    _get_tools_info_payload,
)
from src.tools import _dirty_cache

# ---------------------------------------------------------------------------
# Read-only session info getters ("get_*" socket events)
# ---------------------------------------------------------------------------


@socketio.on("get_pwd")
def handle_get_pwd():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    cwd = _state._session_current_cwd.get(session_id) or os.getcwd()
    socketio.emit("pwd_update", {"path": cwd.replace("\\", "/")}, room=session_id)


@socketio.on("get_skills_info")
def handle_get_skills_info():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    session = _load_session(session_id)
    socketio.emit(
        "skills_info",
        _get_skills_info_payload(session, session_id),
        room=session_id,
    )


@socketio.on("get_system_prompt")
def handle_get_system_prompt():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    socketio.emit(
        "system_prompt",
        {"text": _get_session_system_prompt(session_id)},
        room=session_id,
    )


@socketio.on("get_env_info")
def handle_get_env_info():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    cfg = _state._session_project_config.get(session_id, {})
    socketio.emit(
        "env_info",
        {
            "os": _state._env_os,
            "shell": _state._env_shell,
            "initialCwd": cfg.get("initial_cwd", ""),
        },
        room=session_id,
    )


@socketio.on("get_session_memory_keys")
def handle_get_session_memory_keys():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    keys = _state._get_redis().hkeys(f"session:{session_id}:memory")
    socketio.emit("session_memory_keys_update", {"keys": keys}, room=session_id)


@socketio.on("get_session_memory_value")
def handle_get_session_memory_value(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    key = data.get("key", "")
    value = _state._get_redis().hget(f"session:{session_id}:memory", key)
    if value is not None:
        socketio.emit(
            "session_memory_value",
            {"key": key, "value": value, "found": True},
            room=session_id,
        )
    else:
        socketio.emit(
            "session_memory_value",
            {"key": key, "value": "", "found": False},
            room=session_id,
        )


@socketio.on("get_dirty_cache")
def handle_get_dirty_cache():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    socketio.emit(
        "dirty_cache_update", _dirty_cache.snapshot(session_id), room=session_id
    )


@socketio.on("get_tools_info")
def handle_get_tools_info():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    socketio.emit(
        "tools_info",
        _get_tools_info_payload(session_id),
        room=session_id,
    )
