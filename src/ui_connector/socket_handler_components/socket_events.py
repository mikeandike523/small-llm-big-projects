from __future__ import annotations

import logging
import os

from flask import request
from flask_socketio import emit, join_room
from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components import runtime_settings
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
from src.ui_connector.socket_handler_components.history_loader import (
    cancel_history_load,
)
from src.utils.request_error_formatting import failure_message
from src.utils.session_model import CURRENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Socket event handlers
# ---------------------------------------------------------------------------


@socketio.on("connect")
def handle_connect():
    sid = request.sid
    session_id = request.args.get("sessionId", "")
    if not session_id:
        # Terminal-only connection — no session, sid itself is the room.
        logger.info("Client connected (terminal-only): %s", sid)
        join_room(sid)
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


@socketio.on_error_default
def handle_socket_error(exc: Exception):
    """Report any failure in a socket handler to the client that sent it.

    Handlers do not swallow errors (e.g. a failed MySQL read or write); this
    turns them into a session-level `error` event instead of a silent hang.
    """
    logger.exception("Socket handler %r failed", (request.event or {}).get("message"))
    emit("error", {"message": failure_message(exc)})


@socketio.on("resume_session")
def handle_resume_session(data: dict | None = None):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        return

    # Loading (and repairing an orphaned turn) here, before the client asks for
    # history, guarantees the history loader reads the repaired event log.
    try:
        session = _load_session(session_id)
    except Exception as exc:
        logger.exception("Could not load session %s", session_id)
        emit("session_load_error", {"message": failure_message(exc)})
        return

    skills_path = (
        os.path.join(session.initial_cwd, "skills")
        if session.load_custom_skills_tools
        else None
    )
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
        colored("Session Connected", "green", force_color=True),
        {
            "streaming": True,
            "skills": skills_str,
            "os": _state._env_os,
            "shell": _state._env_shell,
            "initial_cwd": _effective_initial_cwd,
        },
    )

    if session.schema_version != CURRENT_SCHEMA_VERSION:
        emit("session_state", {"schemaInvalid": True})
        return

    # Conversation history is NOT sent here: the client follows up with
    # begin_history_load, which streams it turn by turn (history_loader.py).
    is_turn_active = _state.is_turn_reserved(session_id)
    emit(
        "session_state",
        {
            "startupDone": session.startup_done,
            "isTurnActive": is_turn_active,
            "loadCustomSkillsTools": session.load_custom_skills_tools,
            **runtime_settings.payload(runtime_settings.snapshot(session_id, session)),
        },
    )

    total_cost = _state._session_costs.get(session_id)
    if total_cost is not None:
        emit("session_cost_update", {"total_usd": total_cost})

    last_context_usage = _state._session_last_context_usage.get(session_id)
    # Defensive profile-match check: the snapshot is stamped with the profile
    # that produced it. (_session_from_db already filters on cold load and the
    # profile PATCH handler clears live changes, but this guards any path that
    # leaves a mismatched snapshot in state.) A null known_max_context is a
    # clear signal — never re-emit it as data.
    if (
        last_context_usage
        and last_context_usage.get("known_max_context") is not None
        and last_context_usage.get("profile") == session.profile_name
        and last_context_usage.get("profile_revision")
        == runtime_settings.snapshot(session_id, session).profile_revision
    ):
        emit("context_usage_event", last_context_usage)

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
    cancel_history_load(sid)
    session_id = _state._sid_to_session_id.pop(sid, None)
    if session_id is None:
        # Terminal-only connection — clean up all terminals belonging to this sid.
        for ts in list(_state._terminal_manager.list_sessions()):
            if _state._terminal_session_rooms.get(ts.id) == sid:
                _state._terminal_session_rooms.pop(ts.id, None)
                _state._terminal_opened_by.pop(ts.id, None)
                _state._terminal_manager.destroy(ts.id)
                _state._terminal_output_threads.pop(ts.id, None)
        logger.info("Client disconnected (terminal-only): %s", sid)
        return
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
    cancel_session_turn(session_id)


def cancel_session_turn(session_id: str) -> None:
    """Cancel the session's active turn, exactly as the UI Stop button does.

    Needs no socket request context, so non-socket callers (e.g. the heartbeat
    runner) can use it too.
    """
    # If an approval is pending, pressing Stop is equivalent to "Deny & Stop":
    # resolve the pending approval as denied so the waiting tool executor
    # records the standard denial tool result, and emit approval_resolved so
    # the frontend approval widget clears. event.set() unblocks
    # _request_approval immediately (otherwise it would only notice the cancel
    # via its cancel_event poll, and no denial would be recorded).
    with _state._pending_approvals_lock:
        pending = _state._pending_approvals.get(session_id)
        stopping_pending_approval = pending is not None and pending.get("approved") in (
            None,
            False,
        )
        resolved_pending_approval = (
            pending is not None and pending.get("approved") is None
        )
        if resolved_pending_approval:
            # Only resolve an approval the user has not already decided: a click
            # on the dialog that raced with Stop must not be overridden.
            pending["approved"] = False
            pending["redirect_message"] = None
        pending_cancel_event = (
            pending.get("cancel_event") if stopping_pending_approval else None
        )

    if resolved_pending_approval:
        try:
            _emit_and_log(
                session_id,
                "approval_resolved",
                {
                    "id": pending.get("tool_id"),
                    "approved": False,
                    "turn_id": pending.get("turn_id", ""),
                },
            )
        finally:
            pending["event"].set()
    if stopping_pending_approval:
        # Let the tool worker flush the denied call and every later call in the
        # same assistant exchange before the agent loop exits. Cancelling the
        # asyncio task here would abandon asyncio.to_thread's return value and
        # omit those synthetic tool results from durable turn history.
        if pending_cancel_event is not None:
            pending_cancel_event.set()
    loop, task = _state.get_active_turn_handles(session_id)
    if not stopping_pending_approval and loop is not None and task is not None:
        loop.call_soon_threadsafe(task.cancel)
    logger.info("Cancel requested for session %s", session_id)


@socketio.on("approval_response")
def handle_approval_response(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    tool_id = data.get("id")
    turn_id = data.get("turn_id")
    approved = bool(data.get("approved"))
    rejection_reason = None
    with _state._pending_approvals_lock:
        pending = _state._pending_approvals.get(session_id)
        if pending is None:
            rejection_reason = "no pending approval"
        elif tool_id != pending.get("tool_id"):
            rejection_reason = "tool ID mismatch"
        elif turn_id != pending.get("turn_id"):
            rejection_reason = "turn ID mismatch"
        elif pending.get("approved") is not None:
            rejection_reason = "approval already resolved"
        else:
            pending["approved"] = approved
            pending["redirect_message"] = data.get("redirect_message") or None

    if rejection_reason is not None:
        logger.warning(
            "Approval response rejected (%s): session_id=%s "
            "received_turn_id=%s received_tool_id=%s "
            "expected_turn_id=%s expected_tool_id=%s",
            rejection_reason,
            session_id,
            turn_id,
            tool_id,
            pending.get("turn_id") if pending else None,
            pending.get("tool_id") if pending else None,
        )
        return

    try:
        _emit_and_log(
            session_id,
            "approval_resolved",
            {
                "id": tool_id,
                "approved": approved,
                "turn_id": pending.get("turn_id", ""),
            },
        )
    finally:
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
    _startup_auto_eol = (_startup_cfg.get("system_params") or {}).get(
        "create_file_auto_eol"
    ) or "enabled_silent"
    special_resources: dict = {
        "emit_backend_log": lambda *msgs: _emit_backend_log(session_id, *msgs),
        "session_init_working_dir": session.initial_cwd,
        "session_current_working_dir": _startup_cwd,
        "approval_mode": session.approval_mode,
        "create_file_auto_eol": _startup_auto_eol,
        "on_cwd_change": None,
    }

    def _on_startup_cwd_change(new_path: str) -> None:
        _state._session_current_cwd[session_id] = new_path
        special_resources["session_current_working_dir"] = new_path
        socketio.emit(
            "pwd_update", {"path": new_path.replace("\\", "/")}, room=session_id
        )

    special_resources["on_cwd_change"] = _on_startup_cwd_change
    from src.ui_connector.socket_handler_components.session_store import (
        _get_session_tool_map,
    )

    startup_tool_map = _get_session_tool_map(session_id)

    for i, tc_spec in enumerate(session.startup_tool_calls):
        name = tc_spec.get("name", "")
        # A hand-authored entry in startup_tool_calls.json IS the human's
        # approval for it — request_unredacted (if set) is honored here
        # exactly as execute_tool would honor it for any already-approved
        # call, no stripping.
        args = tc_spec.get("args", {})
        tc_id = f"startup-{i}"

        socketio.emit(
            "startup_tool_call",
            {"id": tc_id, "name": name, "args": args},
            room=session_id,
        )

        try:
            result, _ = execute_tool(
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
