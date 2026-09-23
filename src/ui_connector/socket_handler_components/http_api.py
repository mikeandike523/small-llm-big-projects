from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import uuid as _uuid_module

from flask import request, jsonify
from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import app, socketio
from src.ui_connector import release_notes
from src.ui_connector.socket_handler_components.session_store import (
    _load_session,
    _save_session,
    _delete_session,
    _delete_sessions,
    _init_session_caches,
    _get_session_skill_registry,
    _get_session_tool_map,
    _get_skills_info_payload,
    _get_tools_info_payload,
    _get_session_system_prompt,
)
from src.ui_connector.socket_handler_components.session_customizations import (
    reload_session_customizations,
)
from src.ui_connector.socket_handler_components.emit import _emit_backend_log
from src.ui_connector.socket_handler_components.terminal import (
    _build_starting_environment_info,
)
from src.ui_connector.socket_handler_components.state import SessionToolManifest
from src.utils.sql.session_store_db import list_session_meta
from src.data import get_pool
from src.tools import (
    ALL_TOOL_DEFINITIONS,
    _TOOL_MAP,
    load_custom_tools,
    validate_no_reserved_params,
)
from src.logic.system_prompt import (
    SkillManifestError,
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)
from src.utils.sql.kv_manager import KVManager
from src.utils.param_helper import get_param_value
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.utils.env_info import get_default_workspace_dir
from src.utils.session_model import Session
from src.utils.approval_modes import (
    APPROVAL_MODE_DEFAULT,
    APPROVAL_MODES,
    is_valid_approval_mode,
)
from src.utils.heartbeat_settings import is_valid_heartbeat_settings
from src.utils.startup_tool_calls import validate_startup_tool_calls

logger = logging.getLogger(__name__)


@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    """
    Create a new session with per-session context.
    Body (JSON):
      initial_cwd                   str   — working directory for this session
      load_custom_skills_tools      bool  — load cwd/skills and cwd/tools
      startup_tool_calls_path       str?  — path to startup_tool_calls.json (or null)
      interim_response_as_thinking  bool  — emit interim content tokens as reasoning (default false)
    Returns:
      {"session_id": "<uuid>"}
    """
    data = request.get_json(force=True, silent=True) or {}

    session_id = str(_uuid_module.uuid4())
    initial_cwd = data.get("initial_cwd", "")
    if not initial_cwd or not initial_cwd.strip():
        return (
            jsonify(
                {
                    "error": (
                        "initial_cwd is required. "
                        "If no specific project is needed, pass the global workspace path."
                    )
                }
            ),
            400,
        )
    load_custom_skills_tools = bool(data.get("load_custom_skills_tools", False))
    skills_path = (
        os.path.join(initial_cwd, "skills") if load_custom_skills_tools else None
    )
    custom_tools_path = (
        os.path.join(initial_cwd, "tools") if load_custom_skills_tools else None
    )
    startup_tool_calls_path = data.get("startup_tool_calls_path") or None
    interim_response_as_thinking = bool(data.get("interim_response_as_thinking", False))
    raw_approval_mode = data.get("approval_mode")
    approval_mode = (
        raw_approval_mode.strip()
        if isinstance(raw_approval_mode, str) and raw_approval_mode.strip()
        else APPROVAL_MODE_DEFAULT
    )
    if not is_valid_approval_mode(approval_mode):
        return (
            jsonify(
                {
                    "error": (
                        f"Invalid approval_mode '{approval_mode}'. "
                        f"Must be one of: {', '.join(APPROVAL_MODES)}"
                    )
                }
            ),
            400,
        )

    # Resolve starting profile: explicit override or system default.
    raw_profile = (data.get("profile_name") or "").strip() or None
    if raw_profile is not None:
        try:
            pool = get_pool()
            with pool.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (raw_profile,)
                    )
                    if cur.fetchone() is None:
                        return (
                            jsonify(
                                {"error": f"Profile '{raw_profile}' does not exist."}
                            ),
                            400,
                        )
        except Exception as exc:
            return jsonify({"error": f"Failed to validate profile: {exc}"}), 500
        profile_name: str | None = raw_profile
    else:
        try:
            pool = get_pool()
            with pool.get_connection() as conn:
                profile_name = get_active_profile(KVManager(conn))
        except Exception:
            profile_name = None

    startup_tool_calls: list = []
    _startup_calls_present = False
    if startup_tool_calls_path:
        try:
            with open(startup_tool_calls_path, "r", encoding="utf-8") as fh:
                startup_tool_calls = json.load(fh)
            _startup_calls_present = True
        except FileNotFoundError:
            # No startup_tool_calls.json present — silently skip (no startup tool calls).
            startup_tool_calls = []
        except Exception as exc:
            return (
                jsonify({"error": f"Failed to load startup_tool_calls.json: {exc}"}),
                400,
            )

    session = Session(
        session_id=session_id,
        initial_cwd=initial_cwd,
        load_custom_skills_tools=load_custom_skills_tools,
        startup_tool_calls=startup_tool_calls,
        interim_response_as_thinking=interim_response_as_thinking,
        profile_name=profile_name,
        approval_mode=approval_mode,
    )

    # Validate builtin tools for reserved parameter names before touching session state.
    # Custom tools are validated inside load_custom_tools (raises RuntimeError on violation).
    _builtin_err = validate_no_reserved_params(_TOOL_MAP)
    if _builtin_err:
        return jsonify({"error": _builtin_err}), 400

    # Skills are built before tools: tool loading validates skill-scoped plugin
    # namespaces against the resolved skill id set (see load_custom_tools).
    try:
        registry = build_skill_registry(custom_skills_path=skills_path)
    except SkillManifestError as exc:
        return jsonify({"error": f"Skill loading failed: {exc}"}), 400
    _state._session_skill_registries[session_id] = registry
    session.session_data["__skill_files__"] = registry

    # Pre-validate and cache custom tools so errors surface at creation time.
    if custom_tools_path:
        try:
            result = load_custom_tools(
                tools_dir=custom_tools_path,
                workspace_root=initial_cwd or None,
                session_prefix=session_id[:8],
                known_skill_ids=frozenset(e["id"] for e in registry),
            )
            _excl_load = {
                n for n, f in result.custom_exclusions.items() if f.get("loading")
            }
            base_defs = [
                d
                for d in ALL_TOOL_DEFINITIONS
                if d.get("function", {}).get("name") not in _excl_load
            ] + result.unscoped_defs
            base_map = {k: v for k, v in _TOOL_MAP.items() if k not in _excl_load}
            base_map.update(result.unscoped_map)
            _state._session_tool_sets[session_id] = SessionToolManifest(
                base_defs=base_defs,
                base_map=base_map,
                by_skill=result.by_skill,
                plugins=result.plugins,
            )
        except RuntimeError as exc:
            return jsonify({"error": f"Custom tool loading failed: {exc}"}), 400
    else:
        _state._session_tool_sets[session_id] = SessionToolManifest(
            base_defs=list(ALL_TOOL_DEFINITIONS), base_map=dict(_TOOL_MAP)
        )

    _state._session_system_prompts[session_id] = build_system_prompt(
        starting_environment_info=_build_starting_environment_info(session),
        autoload_entries=get_autoload_skill_entries(registry),
    )
    _state._session_project_config[session_id] = {
        "initial_cwd": initial_cwd,
    }
    _state._session_current_cwd[session_id] = initial_cwd

    # Hard-validate startup_tool_calls against the now-fully-built tool set —
    # same fail-at-creation guarantee as custom tools/skills, rather than a
    # soft "Unknown tool"/"Error executing" string the first time it runs.
    if _startup_calls_present:
        _startup_err = validate_startup_tool_calls(
            session.startup_tool_calls, _get_session_tool_map(session_id)
        )
        if _startup_err:
            return (
                jsonify({"error": f"Invalid startup_tool_calls.json: {_startup_err}"}),
                400,
            )

    _save_session(session_id, session)

    logger.info("Session created: %s cwd=%r", session_id, initial_cwd)
    return jsonify({"session_id": session_id})


@app.route("/api/sessions", methods=["GET"])
def api_list_sessions():
    """
    List all persisted sessions with lightweight metadata.
    Returns a JSON array sorted by created_at descending.
    """
    try:
        rows = list_session_meta()
    except Exception as exc:
        logger.warning("Failed to list sessions from DB: %s", exc)
        return jsonify({"error": f"Failed to list sessions: {exc}"}), 500

    # session_meta rows already carry the denormalized list metadata (turn_count,
    # task_titles, created_at, ...) and arrive ordered by created_at DESC, so no
    # blob parsing or re-sort is needed here.
    results = []
    for row in rows:
        session_id = row["session_id"]
        results.append(
            {
                "session_id": session_id,
                "initial_cwd": row.get("initial_cwd", ""),
                "current_cwd": _state._session_current_cwd.get(session_id)
                or row.get("current_cwd")
                or row.get("initial_cwd", ""),
                "created_at": row.get("created_at", 0.0),
                "turn_count": row.get("turn_count", 0),
                "active_turn": session_id in _state._session_active_turns,
                "task_titles": row.get("task_titles", []),
                "interim_response_as_thinking": row.get(
                    "interim_response_as_thinking", False
                ),
                "load_custom_skills_tools": row.get("load_custom_skills_tools", False),
                "profile_name": row.get("profile_name") or None,
                "corrupt": row.get("corrupt", False),
                "heartbeat_enabled": row.get("heartbeat_enabled", False),
            }
        )
    return jsonify(results)


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def api_delete_session(session_id: str):
    """Delete all data for a session from Redis and in-memory caches."""
    if session_id in _state._session_active_turns:
        return jsonify({"error": "Cannot delete a session with an active turn"}), 409
    _delete_session(session_id)
    logger.info("Session deleted via API: %s", session_id)
    return jsonify({"ok": True})


@app.route("/api/sessions/<session_id>/reload-custom-skills-tools", methods=["POST"])
def api_reload_custom_skills_tools(session_id: str):
    """Reload cwd/skills and cwd/tools for an idle, opted-in session."""
    if session_id in _state._session_active_turns:
        _emit_backend_log(
            session_id,
            colored(
                "Custom skills/tools reload rejected: a turn is active.",
                "red",
                force_color=True,
            ),
        )
        return jsonify({"error": "Cannot reload during an active turn."}), 409

    session = _load_session(session_id)
    if not session.load_custom_skills_tools:
        _emit_backend_log(
            session_id,
            colored(
                "Custom skills/tools reload rejected: loading is disabled for this session.",
                "red",
                force_color=True,
            ),
        )
        return (
            jsonify({"error": "Custom skills and tools are disabled."}),
            409,
        )

    try:
        reload_session_customizations(session, session_id)
    except Exception as exc:
        message = f"Custom skills/tools reload failed: {exc}"
        logger.warning("%s (session %s)", message, session_id)
        _emit_backend_log(session_id, colored(message, "red", force_color=True))
        status = 409 if session_id in _state._session_active_turns else 400
        return jsonify({"error": "Reload failed. See Debug Panel logs."}), status

    _save_session(session_id, session)
    skills_info = _get_skills_info_payload(session, session_id)
    tools_info = _get_tools_info_payload(session_id)
    system_prompt = {"text": _get_session_system_prompt(session_id)}
    socketio.emit("skills_info", skills_info, room=session_id)
    socketio.emit("tools_info", tools_info, room=session_id)
    socketio.emit("system_prompt", system_prompt, room=session_id)
    logger.info("Reloaded custom skills and tools for session %s", session_id)
    return jsonify(
        {
            "ok": True,
            "skills": skills_info["count"],
            "tools": tools_info["totalCount"] - tools_info["builtinCount"],
        }
    )


@app.route("/api/sessions/bulk-delete", methods=["POST"])
def api_bulk_delete_sessions():
    """
    Delete many sessions at once.

    Body (JSON):
      session_ids   list[str] — session ids to delete (may be empty)

    Sessions with an active turn are skipped and reported back so the UI can
    leave them selected rather than silently dropping them.
    Returns:
      {"deleted": [...], "skipped": [...]}
    """
    data = request.get_json(force=True, silent=True) or {}
    raw_ids = data.get("session_ids")
    if not isinstance(raw_ids, list):
        return jsonify({"error": "session_ids must be a list"}), 400

    session_ids: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids:
        if not isinstance(raw, str):
            return jsonify({"error": "session_ids must contain only strings"}), 400
        session_id = raw.strip()
        if not session_id:
            continue
        if session_id not in seen:
            seen.add(session_id)
            session_ids.append(session_id)

    deleted: list[str] = []
    skipped: list[str] = []
    for session_id in session_ids:
        if session_id in _state._session_active_turns:
            skipped.append(session_id)
        else:
            deleted.append(session_id)

    _delete_sessions(deleted)

    if skipped:
        logger.info(
            "Bulk delete skipped %d active session(s): %s", len(skipped), skipped
        )
    if deleted:
        logger.info("Bulk deleted %d session(s) via API", len(deleted))
    return jsonify({"deleted": deleted, "skipped": skipped})


@app.route("/api/sessions/<session_id>/profile", methods=["PATCH"])
def api_session_set_profile(session_id: str):
    """Change the profile for a session (takes effect on the next LLM request)."""
    data = request.get_json(force=True, silent=True) or {}
    profile_name = (data.get("profile_name") or "").strip() or None

    if profile_name is not None:
        try:
            pool = get_pool()
            with pool.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM profiles WHERE name = %s LIMIT 1",
                        (profile_name,),
                    )
                    if cur.fetchone() is None:
                        return (
                            jsonify(
                                {"error": f"Profile '{profile_name}' does not exist."}
                            ),
                            404,
                        )
        except Exception as exc:
            return jsonify({"error": f"DB error: {exc}"}), 500

    session = _load_session(session_id)
    from src.ui_connector.socket_handler_components import runtime_settings

    settings = runtime_settings.set_profile(session_id, session, profile_name)
    session.profile_name = settings.profile_name

    # Every old snapshot describes a request made with the prior profile, even
    # when both profiles happen to advertise the same maximum context size.
    from src.ui_connector.socket_handler_components.emit import clear_context_usage

    clear_context_usage(session_id, profile_name, settings.profile_revision)

    _save_session(session_id, session)
    response = {"ok": True, **runtime_settings.payload(settings)}
    socketio.emit("session_settings_update", response, room=session_id)
    return jsonify(response)


@app.route("/api/sessions/<session_id>/approval-mode", methods=["PATCH"])
def api_session_set_approval_mode(session_id: str):
    """Change the approval mode for the next tool approval check."""
    data = request.get_json(force=True, silent=True) or {}
    raw_approval_mode = data.get("approval_mode")
    approval_mode = (
        raw_approval_mode.strip() if isinstance(raw_approval_mode, str) else ""
    )

    if not is_valid_approval_mode(approval_mode):
        return (
            jsonify(
                {
                    "error": (
                        f"Invalid approval_mode '{approval_mode}'. "
                        f"Must be one of: {', '.join(APPROVAL_MODES)}"
                    )
                }
            ),
            400,
        )

    session = _load_session(session_id)
    from src.ui_connector.socket_handler_components import runtime_settings

    settings = runtime_settings.set_approval_mode(session_id, session, approval_mode)
    session.approval_mode = settings.approval_mode
    _save_session(session_id, session)
    response = {"ok": True, **runtime_settings.payload(settings)}
    socketio.emit("session_settings_update", response, room=session_id)
    return jsonify(response)


@app.route("/api/sessions/<session_id>/heartbeat-settings", methods=["PATCH"])
def api_session_set_heartbeat_settings(session_id: str):
    """Change the heartbeat settings for a session (full replace)."""
    data = request.get_json(force=True, silent=True) or {}
    heartbeat_settings = {
        "enabled": data.get("enabled"),
        "interval_minutes": data.get("interval_minutes"),
        "instructions": data.get("instructions"),
        "heartbeat_approval_policy": data.get("heartbeat_approval_policy"),
    }

    ok, error = is_valid_heartbeat_settings(heartbeat_settings)
    if not ok:
        return jsonify({"error": error}), 400

    session = _load_session(session_id)
    from src.ui_connector.socket_handler_components import runtime_settings

    settings = runtime_settings.set_heartbeat_settings(
        session_id, session, heartbeat_settings
    )
    session.session_data["heartbeat_settings"] = settings.heartbeat_settings
    _save_session(session_id, session)
    response = {"ok": True, **runtime_settings.payload(settings)}
    socketio.emit("session_settings_update", response, room=session_id)
    return jsonify(response)


@app.route("/api/session-defaults", methods=["GET"])
def api_session_defaults():
    """Return default values for all new-session options."""
    defaults = dict(_state._SESSION_DEFAULTS_HARDCODED)
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            profile = get_active_profile(kv)
            if profile is not None:
                prefix = _kv_prefix(profile)
                for param_key, defaults_key in _state._SESSION_DEFAULTS_FROM_DB.items():
                    param_name = param_key[len("params.") :]
                    val = get_param_value(kv, param_name, profile_prefix=prefix)
                    if val is not None:
                        defaults[defaults_key] = val
    except Exception as exc:
        return (
            jsonify({"error": f"Failed to load session defaults from database: {exc}"}),
            500,
        )
    defaults["default_profile"] = profile
    defaults["approval_mode"] = APPROVAL_MODE_DEFAULT
    defaults["approval_modes"] = APPROVAL_MODES
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM profiles ORDER BY name")
                defaults["profiles"] = [r[0] for r in cur.fetchall()]
    except Exception:
        defaults["profiles"] = []
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


@app.route("/api/version", methods=["GET"])
def api_version():
    """
    Return the backend (server) software version, read live from the root
    package.json so it always reflects the currently installed application.
    Paths are resolved against the repository root (not cwd).
    Returns:
      {"version": "<semver>", "note": "<latest release message or ''>",
       "note_date": "<ISO date or ''>"} — "unknown"/"" when data cannot be read.
    """
    note, note_date = release_notes.latest_release_note()
    return jsonify(
        {
            "version": release_notes.read_backend_version(),
            "note": note,
            "note_date": note_date,
        }
    )


@app.route("/api/changelog", methods=["GET"])
def api_changelog_index():
    """
    Return the backend changelog index (releases newest first).
    Returns:
      {"releases": [{"version": "1.2.3", "date": "...", "file": "1.2.3.txt"}, ...]}
      — empty list when no release notes exist yet.
    """
    return jsonify({"releases": release_notes.read_changelog_index()})


@app.route("/api/changelog/<version>", methods=["GET"])
def api_changelog_note(version: str):
    """
    Return the release message for one backend version.
    Returns:
      {"version": "<v>", "message": "<text>"} or 404 when unknown/invalid.
    """
    message = release_notes.read_release_message(version)
    if message is None:
        return jsonify({"error": f"No release notes for version {version}"}), 404
    return jsonify({"version": version, "message": message.strip()})


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
