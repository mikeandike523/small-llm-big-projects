from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid as _uuid_module

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
    _get_session_system_prompt,
    _get_session_skill_registry,
    _get_session_tool_defs,
    _get_session_plugins,
)
from src.ui_connector.socket_handler_components.terminal import (
    _terminal_belongs_to_session,
    _new_terminal_id,
    _next_human_terminal_name,
    _format_cmd_display,
    _get_terminal_meta,
    _terminal_output_pump,
)
from src.ui_connector.socket_handler_components.watchdogs import (
    _is_continuation,
    _get_open_items,
    _fetch_task_title,
)
from src.ui_connector.socket_handler_components.agent_loop import _async_agent_loop
from src.ui_connector.socket_handler_components.llm import (
    _build_traces_xml,
    _rotate_traces_folder,
)
from src.tools import execute_tool, _TOOL_MAP
from src.tools import _dirty_cache
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui
from src.utils.llm.factory import load_llm_config, make_llm_from_config
from src.utils.session_model import (
    Session,
    Turn,
    Subturn,
    turn_to_dict,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.event_log import get_events_since

logger = logging.getLogger(__name__)


def _load_llm_config() -> dict | None:
    """Return dict with endpoint_url, token_value, model or None on failure."""
    return load_llm_config()


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


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    session_id = _state._sid_to_session_id.pop(sid, None)
    logger.info("Client disconnected: %s (session=%s)", sid, session_id)
    pending = _state._pending_approvals.pop(sid, None)
    if pending and not pending["event"].is_set():
        pending["approved"] = False
        pending["event"].set()


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
    skills_path = session.skills_path
    if skills_path:
        custom_skills = [
            entry
            for entry in _get_session_skill_registry(session_id)
            if entry["source"] == "custom"
        ]
        skill_labels = sorted(
            f"{entry['name']} ({entry['id']})"
            + (" [autoload]" if entry["autoload"] else "")
            for entry in custom_skills
        )
        socketio.emit(
            "skills_info",
            {
                "enabled": True,
                "count": len(skill_labels),
                "path": skills_path.replace("\\", "/"),
                "files": skill_labels,
            },
            room=session_id,
        )
    else:
        socketio.emit(
            "skills_info",
            {
                "enabled": False,
                "count": 0,
                "path": None,
                "files": [],
            },
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
    tool_defs = _get_session_tool_defs(session_id)
    plugins = _get_session_plugins(session_id)
    total = len(tool_defs)
    custom_count = sum(p["count"] for p in plugins)
    socketio.emit(
        "tools_info",
        {
            "totalCount": total,
            "builtinCount": total - custom_count,
            "builtinPath": "src/tools/",
            "names": [d["function"]["name"] for d in tool_defs],
            "customPlugins": plugins if plugins else None,
        },
        room=session_id,
    )


@socketio.on("approval_response")
def handle_approval_response(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid, sid)
    tool_id = data.get("id")
    approved = bool(data.get("approved"))
    pending = _state._pending_approvals.get(sid)
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


@socketio.on("save_traces")
def handle_save_traces():
    """Flush the session trace buffer to an XML file in _traces_dir."""
    from datetime import datetime, timezone
    import uuid as _uuid

    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        emit("traces_saved", {"count": 0, "filename": None})
        return

    buf = _state._session_trace_buffers.get(session_id)
    if not buf:
        emit("traces_saved", {"count": 0, "filename": None})
        return

    entries = []
    while buf:
        entries.append(buf.popleft())

    if not entries:
        emit("traces_saved", {"count": 0, "filename": None})
        return

    try:
        os.makedirs(_state._traces_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        short_id = str(_uuid.uuid4())[:8]
        filename = f"{timestamp}_{short_id}.xml"
        filepath = os.path.join(_state._traces_dir, filename)

        xml = _build_traces_xml(session_id, entries)
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(xml)

        _rotate_traces_folder()

        emit("traces_saved", {"count": len(entries), "filename": filename})
    except Exception as exc:
        logger.warning("Failed to save traces: %s", exc)
        emit("traces_save_error", {"message": str(exc)})


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
    if _startup_cwd:
        try:
            os.chdir(_startup_cwd)
        except OSError as _chdir_err:
            socketio.emit(
                "backend_log",
                {"text": f"Warning: could not chdir to {_startup_cwd!r}: {_chdir_err}"},
                room=session_id,
            )

    special_resources = {
        "on_log": lambda msg: _emit_backend_log(session_id, msg),
        "initial_cwd": session.initial_cwd,
    }
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

        if name == "change_pwd":
            _state._session_current_cwd[session_id] = os.getcwd()
            socketio.emit(
                "pwd_update", {"path": os.getcwd().replace("\\", "/")}, room=session_id
            )

    session.startup_done = True
    _save_session(session_id, session)
    socketio.emit(
        "startup_tool_calls_done",
        {"count": len(session.startup_tool_calls)},
        room=session_id,
    )


@socketio.on("user_message")
def handle_user_message(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    if session_id in _state._cancel_tasks:
        emit(
            "error",
            {"message": "A turn is already in progress. Please wait or cancel first."},
        )
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    turn_id: str = data.get("clientTurnId") or ""
    if not turn_id:
        turn_id = str(_uuid_module.uuid4())

    llm_config = _load_llm_config()
    if llm_config is None:
        _emit_and_log(
            session_id,
            "error",
            {
                "message": "No active token/endpoint configured. Run `slbp token use` first.",
                "turn_id": turn_id,
            },
        )
        return

    streaming_llm = make_llm_from_config(llm_config, timeout_s=60)
    return_value_max_chars: int | None = llm_config["system_params"].get(
        "return_value_max_chars"
    )
    watchdog_max_tokens: int | None = llm_config["system_params"].get(
        "watchdog_max_tokens"
    )
    title_summary_max_tokens: int | None = llm_config["system_params"].get(
        "title_summary_max_tokens"
    )

    session = _load_session(session_id)

    _effective_cwd = _state._session_current_cwd.get(session_id) or session.initial_cwd
    if _effective_cwd:
        try:
            os.chdir(_effective_cwd)
        except OSError as _chdir_err:
            _emit_backend_log(
                session_id,
                f"Warning: could not chdir to {_effective_cwd!r}: {_chdir_err}",
            )

    user_text_with_context = text

    followup_behavior = data.get("followup_behavior", "auto")
    _is_cont = False
    if followup_behavior == "follow-up":
        _is_cont = bool(session.completed_turns)
    elif followup_behavior == "new-task":
        _is_cont = False
    elif session.completed_turns:
        _loop_for_watchdog = asyncio.new_event_loop()
        try:
            _is_cont = _loop_for_watchdog.run_until_complete(
                _is_continuation(streaming_llm, session, text, watchdog_max_tokens)
            )
        except Exception as _wdog_exc:
            logger.warning("Continuation watchdog error: %s", _wdog_exc)
            _is_cont = False
        finally:
            _loop_for_watchdog.close()

    subturn_id = str(_uuid_module.uuid4())
    if _is_cont:
        current_turn = session.completed_turns.pop()
        current_turn.completed = False
        current_subturn = Subturn(
            id=subturn_id,
            user_text=text,
            user_text_with_context=user_text_with_context,
            is_continuation=True,
        )
        current_turn.subturns.append(current_subturn)
        turn_id = current_turn.id
    else:
        current_subturn = Subturn(
            id=subturn_id,
            user_text=text,
            user_text_with_context=user_text_with_context,
            is_continuation=False,
        )
        current_turn = Turn(
            id=turn_id,
            subturns=[current_subturn],
        )

    session.current_turn = current_turn

    _emit_and_log(
        session_id,
        "turn_start",
        {
            "turn_id": turn_id,
            "user_text": text,
            "subturn_id": subturn_id,
        },
    )

    _existing_todos = session.session_data.get("todo_list") or []
    if not _is_cont:
        session.session_data["todo_list"] = []
        _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})
    elif _existing_todos and not _get_open_items(_existing_todos):
        session.session_data["todo_list"] = []
        _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})
    elif _existing_todos:
        _emit_and_log(
            session_id,
            "todo_list_update",
            {
                "items": _todo_format_items_for_ui(_existing_todos),
                "turn_id": turn_id,
            },
        )

    cancel_event = threading.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _state._cancel_loops[session_id] = loop

    async def _fetch_and_store_title() -> None:
        title = await _fetch_task_title(streaming_llm, text, title_summary_max_tokens)
        if title:
            current_turn.task_title = title
            _emit_and_log(
                session_id, "task_title", {"turn_id": turn_id, "title": title}
            )
            _save_session(session_id, session)

    async def _run() -> None:
        task = asyncio.current_task()
        _state._cancel_tasks[session_id] = task
        try:
            _had_tool_calls = await _async_agent_loop(
                sid,
                session_id,
                session,
                streaming_llm,
                turn_id,
                current_turn,
                current_subturn,
                return_value_max_chars,
                cancel_event,
                watchdog_max_tokens=watchdog_max_tokens,
            )
            if _had_tool_calls and not current_turn.task_title:
                await _fetch_and_store_title()
        except asyncio.CancelledError:
            cancel_event.set()
        except Exception as exc:
            logger.exception(
                "Unhandled exception in agent loop for session %s: %s", session_id, exc
            )
        finally:
            _state._cancel_tasks.pop(session_id, None)
            _state._cancel_loops.pop(session_id, None)

    _state._session_active_turns.add(session_id)
    try:
        loop.run_until_complete(_run())
    finally:
        _state._session_active_turns.discard(session_id)
        loop.close()


@socketio.on("force_continuation")
def handle_force_continuation(data: dict):
    """Force a continuation subturn, bypassing the continuation watchdog."""
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    if session_id in _state._cancel_tasks:
        emit(
            "error",
            {"message": "A turn is already in progress. Please wait or cancel first."},
        )
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    if not _state._sid_to_session_id.get(sid):
        return

    llm_config = _load_llm_config()
    if llm_config is None:
        emit(
            "error",
            {
                "message": "No active token/endpoint configured. Run `slbp token use` first."
            },
        )
        return

    session = _load_session(session_id)

    if not session.completed_turns:
        emit("error", {"message": "No previous turn to continue."})
        return

    streaming_llm = make_llm_from_config(llm_config, timeout_s=60)
    return_value_max_chars: int | None = llm_config["system_params"].get(
        "return_value_max_chars"
    )
    watchdog_max_tokens: int | None = llm_config["system_params"].get(
        "watchdog_max_tokens"
    )

    _effective_cwd = _state._session_current_cwd.get(session_id) or session.initial_cwd
    if _effective_cwd:
        try:
            os.chdir(_effective_cwd)
        except OSError as _chdir_err:
            _emit_backend_log(
                session_id,
                f"Warning: could not chdir to {_effective_cwd!r}: {_chdir_err}",
            )

    current_turn = session.completed_turns.pop()
    current_turn.completed = False

    subturn_id = str(_uuid_module.uuid4())
    turn_id = current_turn.id
    current_subturn = Subturn(
        id=subturn_id,
        user_text=text,
        user_text_with_context=text,
        is_continuation=True,
    )
    current_turn.subturns.append(current_subturn)
    session.current_turn = current_turn

    _emit_and_log(
        session_id,
        "turn_start",
        {
            "turn_id": turn_id,
            "user_text": text,
            "subturn_id": subturn_id,
        },
    )

    _fc_existing_todos = session.session_data.get("todo_list") or []
    if _fc_existing_todos and not _get_open_items(_fc_existing_todos):
        session.session_data["todo_list"] = []
        _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})
    elif _fc_existing_todos:
        _emit_and_log(
            session_id,
            "todo_list_update",
            {
                "items": _todo_format_items_for_ui(_fc_existing_todos),
                "turn_id": turn_id,
            },
        )

    cancel_event = threading.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _state._cancel_loops[session_id] = loop

    async def _run() -> None:
        task = asyncio.current_task()
        _state._cancel_tasks[session_id] = task
        try:
            await _async_agent_loop(
                sid,
                session_id,
                session,
                streaming_llm,
                turn_id,
                current_turn,
                current_subturn,
                return_value_max_chars,
                cancel_event,
                watchdog_max_tokens=watchdog_max_tokens,
            )
        except asyncio.CancelledError:
            cancel_event.set()
        except Exception as exc:
            logger.exception(
                "Unhandled exception in force_continuation loop for session %s: %s",
                session_id,
                exc,
            )
        finally:
            _state._cancel_tasks.pop(session_id, None)
            _state._cancel_loops.pop(session_id, None)

    _state._session_active_turns.add(session_id)
    try:
        loop.run_until_complete(_run())
    finally:
        _state._session_active_turns.discard(session_id)
        loop.close()
