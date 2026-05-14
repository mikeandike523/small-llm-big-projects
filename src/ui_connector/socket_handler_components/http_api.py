from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import uuid as _uuid_module
from collections import deque

from flask import request, jsonify

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import app
from src.ui_connector.socket_handler_components.session_store import (
    _save_session,
    _delete_session,
    _init_session_caches,
    _get_session_skill_registry,
)
from src.ui_connector.socket_handler_components.terminal import (
    _build_starting_environment_info,
)
from src.data import get_pool
from src.tools import ALL_TOOL_DEFINITIONS, _TOOL_MAP, load_custom_tools
from src.logic.system_prompt import (
    SkillManifestError,
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.utils.env_info import get_default_workspace_dir
from src.utils.session_model import Session

logger = logging.getLogger(__name__)


@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    """
    Create a new session with per-session context.
    Body (JSON):
      initial_cwd                   str   — working directory for this session
      skills_path                   str?  — path to skills/ directory (or null)
      custom_tools_path             str?  — path to tools/ directory (or null)
      startup_tool_calls_path       str?  — path to startup_tool_calls.json (or null)
      interim_response_as_thinking  bool  — emit interim content tokens as reasoning (default false)
    Returns:
      {"session_id": "<uuid>"}
    """
    data = request.get_json(force=True, silent=True) or {}

    session_id = str(_uuid_module.uuid4())
    initial_cwd = data.get("initial_cwd", "")
    skills_path = data.get("skills_path") or None
    custom_tools_path = data.get("custom_tools_path") or None
    startup_tool_calls_path = data.get("startup_tool_calls_path") or None
    interim_response_as_thinking = bool(data.get("interim_response_as_thinking", False))
    record_traces = bool(data.get("record_traces", False))

    startup_tool_calls: list = []
    if startup_tool_calls_path:
        try:
            with open(startup_tool_calls_path, "r", encoding="utf-8") as fh:
                startup_tool_calls = json.load(fh)
        except FileNotFoundError:
            return (
                jsonify(
                    {
                        "error": f"startup_tool_calls.json not found at {startup_tool_calls_path!r}"
                    }
                ),
                400,
            )
        except Exception as exc:
            return (
                jsonify({"error": f"Failed to load startup_tool_calls.json: {exc}"}),
                400,
            )

    session = Session(
        session_id=session_id,
        initial_cwd=initial_cwd,
        skills_path=skills_path,
        custom_tools_path=custom_tools_path,
        startup_tool_calls=startup_tool_calls,
        interim_response_as_thinking=interim_response_as_thinking,
        record_traces=record_traces,
    )

    if record_traces:
        _state._session_trace_buffers[session_id] = deque()

    # Pre-validate and cache custom tools so errors surface at creation time.
    if custom_tools_path:
        try:
            extra_defs, extra_map, plugins = load_custom_tools(
                tools_dir=custom_tools_path,
                workspace_root=initial_cwd or None,
                session_prefix=session_id[:8],
            )
            _state._session_tool_sets[session_id] = (
                list(ALL_TOOL_DEFINITIONS) + extra_defs,
                {**_TOOL_MAP, **extra_map},
                plugins,
            )
        except RuntimeError as exc:
            return jsonify({"error": f"Custom tool loading failed: {exc}"}), 400
    else:
        _state._session_tool_sets[session_id] = (ALL_TOOL_DEFINITIONS, _TOOL_MAP, [])

    try:
        registry = build_skill_registry(custom_skills_path=skills_path)
    except SkillManifestError as exc:
        return jsonify({"error": f"Skill loading failed: {exc}"}), 400
    _state._session_skill_registries[session_id] = registry
    session.session_data["__skill_files__"] = registry
    _state._session_system_prompts[session_id] = build_system_prompt(
        starting_environment_info=_build_starting_environment_info(session),
        autoload_entries=get_autoload_skill_entries(registry),
    )
    _state._session_project_config[session_id] = {
        "initial_cwd": initial_cwd,
    }
    _state._session_current_cwd[session_id] = initial_cwd

    _save_session(session_id, session)

    logger.info("Session created: %s cwd=%r", session_id, initial_cwd)
    return jsonify({"session_id": session_id})


@app.route("/api/sessions", methods=["GET"])
def api_list_sessions():
    """
    List all persisted sessions with lightweight metadata.
    Returns a JSON array sorted by created_at descending.
    """
    r = _state._get_redis()
    results = []
    for raw_key in r.scan_iter("session:*"):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        # Skip sub-keys like session:{id}:events, session:{id}:memory
        parts = key.split(":")
        if len(parts) != 2:
            continue
        session_id = parts[1]
        raw = r.get(key)
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        completed_turns = d.get("completed_turns") or []
        current_turn = d.get("current_turn")
        turn_count = len(completed_turns) + (1 if current_turn else 0)
        task_titles = [t["task_title"] for t in completed_turns if t.get("task_title")]
        if current_turn and current_turn.get("task_title"):
            task_titles.append(current_turn["task_title"])
        results.append(
            {
                "session_id": session_id,
                "initial_cwd": d.get("initial_cwd", ""),
                "current_cwd": _state._session_current_cwd.get(session_id)
                or d.get("initial_cwd", ""),
                "created_at": d.get("created_at", 0.0),
                "turn_count": turn_count,
                "active_turn": session_id in _state._session_active_turns,
                "task_titles": task_titles,
                "interim_response_as_thinking": d.get(
                    "interim_response_as_thinking", False
                ),
                "record_traces": d.get("record_traces", False),
                "skills_path": d.get("skills_path") or None,
                "custom_tools_path": d.get("custom_tools_path") or None,
            }
        )
    results.sort(key=lambda s: s["created_at"], reverse=True)
    return jsonify(results)


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def api_delete_session(session_id: str):
    """Delete all data for a session from Redis and in-memory caches."""
    if session_id in _state._session_active_turns:
        return jsonify({"error": "Cannot delete a session with an active turn"}), 409
    _delete_session(session_id)
    logger.info("Session deleted via API: %s", session_id)
    return jsonify({"ok": True})


@app.route("/api/session-defaults", methods=["GET"])
def api_session_defaults():
    """Return default values for all new-session options."""
    defaults = dict(_state._SESSION_DEFAULTS_HARDCODED)
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            profile = get_active_profile(kv)
            prefix = _kv_prefix(profile)
            for param_key, defaults_key in _state._SESSION_DEFAULTS_FROM_DB.items():
                val = kv.get_value(prefix + param_key)
                if val is not None:
                    defaults[defaults_key] = val
    except Exception as exc:
        return (
            jsonify({"error": f"Failed to load session defaults from database: {exc}"}),
            500,
        )
    return jsonify(defaults)


@app.route("/api/system-info", methods=["GET"])
def api_system_info():
    """Return basic system information useful for the dashboard."""
    return jsonify(
        {
            "home_dir": str(pathlib.Path.home()).replace("\\", "/"),
            "workspace_dir": get_default_workspace_dir(),
        }
    )


@app.route("/api/folder-pick", methods=["POST"])
def api_folder_pick():
    """
    Open a native OS folder-picker dialog (tkinter) in a subprocess and return
    the chosen path.  Returns {"path": "<chosen>"} or {"path": null} if cancelled.
    """
    data = request.get_json(force=True, silent=True) or {}
    initial_dir = data.get("initial_dir") or str(pathlib.Path.home())

    script = (
        "import tkinter, tkinter.filedialog, sys; "
        "root = tkinter.Tk(); root.withdraw(); root.wm_attributes('-topmost', 1); "
        f"result = tkinter.filedialog.askdirectory(initialdir={initial_dir!r}, title='Select working directory'); "
        "print(result or '', end='')"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        chosen = proc.stdout.strip() or None
    except subprocess.TimeoutExpired:
        chosen = None
    except Exception as exc:
        return jsonify({"error": str(exc), "path": None}), 500

    if chosen:
        chosen = chosen.replace("\\", "/")
    return jsonify({"path": chosen})
