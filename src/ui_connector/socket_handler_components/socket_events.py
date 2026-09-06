from __future__ import annotations

import logging

from flask import request
from flask_socketio import emit, join_room
from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
)
from src.ui_connector.socket_handler_components.session_store import (
    _load_session,
    _save_session,
    _get_session_skill_registry,
)
from src.ui_connector.socket_handler_components.terminal import _format_cmd_display
from src.tools import execute_tool
from src.utils.llm.factory import load_llm_config
from src.utils.session_model import turn_to_dict, CURRENT_SCHEMA_VERSION
from src.utils.event_log import get_events_since

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Socket event handlers
# ---------------------------------------------------------------------------


@socketio.on("connect")
def handle_connect():
    sid = request.sid
    session_id = request.args.get("sessionId", "")
    if not session_id:
        logger.warning("Client connected without sessionId: %s", sid)
        return

    existing = [
        s
        for s, sess in _state._sid_to_session_id.items()
        if sess == session_id and s != sid
    ]
    if existing:
        logger.warning(
            "Session %s already has active SID(s) %s. New SID %s also joining. Multi-tab is not supported.",
            session_id,
            existing,
            sid,
        )

    logger.info("Client connected: %s -> session %s", sid, session_id)
    _state._sid_to_session_id[sid] = session_id
    join_room(session_id)


@socketio.on("resume_session")
def handle_resume_session(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return

    last_event_id = data.get("lastEventId", "0-0")
    session = _load_session(session_id)

    skills_path = session.skills_path
    if skills_path:
        custom_skills = [
            entry
            for entry in _get_session_skill_registry(session_id)
            if entry["source"] == "custom"
        ]
        skills_str = f"enabled ({len(custom_skills)} skills)"
    else:
        skills_str = "disabled"
    _effective_initial_cwd = session.initial_cwd or "(none)"
    _emit_backend_log(
        session_id,
        colored("System started", "green")
        + f": streaming=True, skills={skills_str}, os={_state._env_os}, shell={_state._env_shell}, "
        f"initial_cwd={_effective_initial_cwd!r}",
    )

    if session.schema_version != CURRENT_SCHEMA_VERSION:
        emit("session_state", {"schemaInvalid": True})
        return

    completed_turns_data = [turn_to_dict(t) for t in session.completed_turns]
    current_turn_data = (
        turn_to_dict(session.current_turn) if session.current_turn else None
    )
    is_turn_active = session_id in _state._cancel_tasks
    emit(
        "session_state",
        {
            "startupDone": session.startup_done,
            "completedTurns": completed_turns_data,
            "currentTurn": current_turn_data,
            "isTurnActive": is_turn_active,
            "profileName": session.profile_name,
        },
    )

    total_cost = _state._session_costs.get(session_id)
    if total_cost is not None:
        emit("session_cost_update", {"total_usd": total_cost})

    try:
        r = _state._get_redis()
        events = get_events_since(r, session_id, last_event_id)
    except Exception as exc:
        logger.warning("Event replay error for session %s: %s", session_id, exc)
        events = []
    emit("event_replay", {"events": events, "replay_complete": True})

    try:
        from src.tools.host_shell import get_active_output

        snapshot = get_active_output(session_id)
        if snapshot is not None:
            emit("shell_output_snapshot", {"output": snapshot})
    except Exception as exc:
        logger.warning(
            "shell_output_snapshot error for session %s: %s", session_id, exc
        )

    sessions = [
        s
        for s in _state._terminal_manager.list_sessions()
        if _state._terminal_session_rooms.get(s.id) == session_id
        and s.process.is_alive()
    ]
    emit(
        "terminal_sessions_state",
        {
            "sessions": [
                {
                    "terminal_id": s.id,
                    "name": s.name,
                    "snapshot": s.get_snapshot(),
                    "cmd_display": _format_cmd_display(s.cmd),
                }
                for s in sessions
            ],
        },
    )


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    session_id = _state._sid_to_session_id.pop(sid, None)
    logger.info("Client disconnected: %s (session=%s)", sid, session_id)
    # Pending approvals are keyed by session_id and wait indefinitely (see
    # approval.py) — a dropped connection (e.g. the client's machine sleeps)
    # must NOT resolve them. The reconnect that follows resumes the same
    # session_id and can still approve/deny the still-pending request.


@socketio.on("cancel_turn")
def handle_cancel_turn():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return
    loop = _state._cancel_loops.get(session_id)
    task = _state._cancel_tasks.get(session_id)
    if loop is not None and task is not None:
        loop.call_soon_threadsafe(task.cancel)
    logger.info("Cancel requested for session %s", session_id)


@socketio.on("approval_response")
def handle_approval_response(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    tool_id = data.get("id")
    approved = bool(data.get("approved"))
    pending = _state._pending_approvals.get(session_id)
    if pending:
        pending["approved"] = approved
        pending["redirect_message"] = data.get("redirect_message") or None
        _emit_and_log(
            session_id,
            "approval_resolved",
            {
                "id": tool_id,
                "approved": approved,
                "turn_id": pending.get("turn_id", ""),
            },
        )
        pending["event"].set()


@socketio.on("run_startup_tool_calls")
def handle_run_startup_tool_calls():
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        emit("startup_tool_calls_done", {"count": 0})
        return

    session = _load_session(session_id)

    if not session.startup_tool_calls:
        socketio.emit("startup_tool_calls_done", {"count": 0}, room=session_id)
        return

    if session.startup_done:
        socketio.emit(
            "startup_tool_calls_done", {"count": 0, "skipped": True}, room=session_id
        )
        return

    _startup_cwd = _state._session_current_cwd.get(session_id) or session.initial_cwd
    _startup_cfg = load_llm_config(session.profile_name) or {}
    _startup_auto_eol = (
        (_startup_cfg.get("system_params") or {}).get("create_file_auto_eol")
        or "enabled_silent"
    )
    special_resources: dict = {
        "emit_backend_log": lambda *msgs: _emit_backend_log(session_id, *msgs),
        "initial_cwd": session.initial_cwd,
        "session_cwd": _startup_cwd,
        "create_file_auto_eol": _startup_auto_eol,
        "on_cwd_change": None,
    }

    def _on_startup_cwd_change(new_path: str) -> None:
        _state._session_current_cwd[session_id] = new_path
        special_resources["session_cwd"] = new_path
        socketio.emit("pwd_update", {"path": new_path.replace("\\", "/")}, room=session_id)

    special_resources["on_cwd_change"] = _on_startup_cwd_change
    from src.ui_connector.socket_handler_components.session_store import (
        _get_session_tool_map,
    )

    startup_tool_map = _get_session_tool_map(session_id)

    for i, tc_spec in enumerate(session.startup_tool_calls):
        name = tc_spec.get("name", "")
        args = tc_spec.get("args", {})
        tc_id = f"startup-{i}"

        socketio.emit(
            "startup_tool_call",
            {"id": tc_id, "name": name, "args": args},
            room=session_id,
        )

        try:
            result = execute_tool(
                name,
                args,
                session.session_data,
                special_resources,
                tool_map=startup_tool_map,
            )
        except Exception as exc:
            result = f"Error executing '{name}': {exc}"

        socketio.emit(
            "startup_tool_result", {"id": tc_id, "result": result}, room=session_id
        )

    session.startup_done = True
    _save_session(session_id, session)
    socketio.emit(
        "startup_tool_calls_done",
        {"count": len(session.startup_tool_calls)},
        room=session_id,
    )
