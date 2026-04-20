from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any

import httpx
import redis
import uuid as _uuid_module
from flask import request, jsonify
from flask_socketio import emit, join_room

from src.ui_connector.app import app, socketio
from src.data import get_pool

from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.utils.llm.factory import load_llm_config
from src.tools import ALL_TOOL_DEFINITIONS, execute_tool, check_needs_approval, _TOOL_MAP, load_custom_tools
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui
from src.logic.system_prompt import build_system_prompt, build_skill_registry
from src.utils.conversation_strip import strip_down_messages
from src.utils.emitting_kv_manager import EmittingKVManager
from src.utils.redis_dict import RedisDict
from src.utils.request_error_formatting import format_http_error
from src.utils.env_info import format_environment_info, get_default_workspace_dir, get_os, get_shell
from src.utils.session_model import (
    Session, Turn, LLMExchange, ToolCallRecord, CompactionRecord,
    session_to_dict, session_from_dict, turn_to_dict, turn_from_dict,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.event_log import log_event, get_events_since, REPLAY_EXCLUDED_EVENTS
from src.utils.exceptions import ToolHangError, ToolTimeoutError
from src.utils.docker_compose import get_service_port
from src.utils.compaction_transcript import build_compaction_messages
from termcolor import colored

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT: str = build_system_prompt()
_BASE_SKILL_REGISTRY: list[dict] = build_skill_registry()

_env_os = get_os()
_env_shell = get_shell()
_hotfix_bad_parser: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER") == "1"
_hotfix_void_call: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL") == "1"

# Trace recording config (set by slbp server run)
_server_cwd: str = os.environ.get("SLBP_SERVER_CWD", os.getcwd())
_traces_dir: str = os.path.join(_server_cwd, ".slbp-traces")
_trace_folder_max_bytes: int | None = (
    int(float(os.environ["SLBP_TRACE_FOLDER_MAX_GB"]) * 1024 ** 3)
    if "SLBP_TRACE_FOLDER_MAX_GB" in os.environ
    else None
)

# ---------------------------------------------------------------------------
# Per-session state caches (rebuilt from session data on load)
# ---------------------------------------------------------------------------

# session_id -> (tool_definitions, tool_map, plugin_info_list)
_session_tool_sets: dict[str, tuple[list, dict, list]] = {}
# session_id -> system_prompt_string
_session_system_prompts: dict[str, str] = {}
# session_id -> list of skill file descriptors {title, filename, path, source}
_session_skill_registries: dict[str, list[dict]] = {}
# session_id -> {initial_cwd, pin_project_memory} — lightweight cache for info handlers
_session_project_config: dict[str, dict] = {}
# session_id -> current working directory for this session (updated by change_pwd tool)
_session_current_cwd: dict[str, str] = {}
# session_id -> deque of TraceEntry objects (only populated when session.record_traces=True)
_session_trace_buffers: dict[str, deque] = {}
# Set of session_ids that are currently executing a turn
_session_active_turns: set[str] = set()


def _build_starting_environment_info(session: "Session") -> str:
    """
    Build the one-time environment snapshot embedded in the per-session system prompt.
    """
    snapshot_cwd = session.initial_cwd or os.getcwd()
    return format_environment_info(
        current_cwd=snapshot_cwd,
        initial_cwd=session.initial_cwd or None,
    )


def _get_default_project(session_id: str) -> str:
    cfg = _session_project_config.get(session_id, {})
    if cfg.get("pin_project_memory", True):
        return cfg.get("initial_cwd", "") or os.getcwd()
    return os.getcwd()


def _get_session_tool_defs(session_id: str) -> list[dict]:
    return _session_tool_sets.get(session_id, (ALL_TOOL_DEFINITIONS, _TOOL_MAP, []))[0]


def _get_session_tool_map(session_id: str) -> dict:
    return _session_tool_sets.get(session_id, (ALL_TOOL_DEFINITIONS, _TOOL_MAP, []))[1]


def _get_session_plugins(session_id: str) -> list[dict]:
    return _session_tool_sets.get(session_id, (ALL_TOOL_DEFINITIONS, _TOOL_MAP, []))[2]


def _get_session_system_prompt(session_id: str) -> str:
    return _session_system_prompts.get(session_id, _BASE_SYSTEM_PROMPT)


def _init_session_caches(session: "Session", session_id: str) -> None:
    """Build per-session tool set and system prompt caches (idempotent — skips if already done)."""
    if session_id not in _session_tool_sets:
        if session.custom_tools_path:
            try:
                extra_defs, extra_map, plugins = load_custom_tools(
                    tools_dir=session.custom_tools_path,
                    workspace_root=session.initial_cwd or None,
                    session_prefix=session_id[:8],
                )
                tool_defs = list(ALL_TOOL_DEFINITIONS) + extra_defs
                tool_map = {**_TOOL_MAP, **extra_map}
            except RuntimeError as exc:
                logger.error("Custom tool loading failed for session %s: %s", session_id, exc)
                tool_defs = list(ALL_TOOL_DEFINITIONS)
                tool_map = dict(_TOOL_MAP)
                plugins = []
        else:
            tool_defs = ALL_TOOL_DEFINITIONS
            tool_map = _TOOL_MAP
            plugins = []
        _session_tool_sets[session_id] = (tool_defs, tool_map, plugins)

    if session_id not in _session_system_prompts:
        _session_system_prompts[session_id] = build_system_prompt(
            starting_environment_info=_build_starting_environment_info(session),
        )

    if session_id not in _session_skill_registries:
        registry = build_skill_registry(custom_skills_path=session.skills_path)
        _session_skill_registries[session_id] = registry
        session.session_data["__skill_files__"] = registry
    else:
        session.session_data["__skill_files__"] = _session_skill_registries[session_id]

    _session_project_config[session_id] = {
        "initial_cwd": session.initial_cwd,
        "pin_project_memory": session.pin_project_memory,
    }

    # Track per-session CWD; only initialise if not already set so mid-session
    # navigation (change_pwd) survives across calls to _init_session_caches.
    if session_id not in _session_current_cwd:
        _session_current_cwd[session_id] = session.initial_cwd

    # Re-create the trace buffer if the session was loaded from Redis after a restart.
    if session.record_traces and session_id not in _session_trace_buffers:
        _session_trace_buffers[session_id] = deque()


# ---------------------------------------------------------------------------
# SID → session_id mapping (cleaned up on disconnect, NOT on session end)
# ---------------------------------------------------------------------------

_sid_to_session_id: dict[str, str] = {}

# Asyncio cancellation: maps session_id -> (event_loop, asyncio.Task)
# Replaces the old threading.Event _cancel_flags dict.
_cancel_loops: dict[str, asyncio.AbstractEventLoop] = {}
_cancel_tasks: dict[str, asyncio.Task] = {}

# Stop-and-redirect: soft interrupt that injects guidance without ending the turn.
# redirect_event is set by handle_stop_and_redirect; the loop injects the message
# as user_continuation and continues (unlike cancel_event which ends the turn).
_redirect_events: dict[str, threading.Event] = {}
_redirect_messages: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Backend log emitter
# ---------------------------------------------------------------------------

_log_counter = 0
_log_counter_lock = threading.Lock()


def _emit_backend_log(session_id: str, text: str) -> None:
    global _log_counter
    with _log_counter_lock:
        _log_counter += 1
        n = _log_counter
    socketio.emit("backend_log", {"id": n, "text": text}, room=session_id)


# ---------------------------------------------------------------------------
# Event log + emit helper
# ---------------------------------------------------------------------------

def _emit_and_log(session_id: str, event_type: str, data: dict) -> None:
    """Emit a socket event to the session room and log it to Redis Streams (if not excluded)."""
    if event_type not in REPLAY_EXCLUDED_EVENTS:
        try:
            r = _get_redis()
            event_id = log_event(r, session_id, event_type, data)
            data = {**data, "event_id": event_id}
        except Exception as exc:
            logger.warning("Failed to log event %r: %s", event_type, exc)
    socketio.emit(event_type, data, room=session_id)


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# Maps socket session ID to {"event": threading.Event, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}


def _request_approval(
    sid: str,
    session_id: str,
    tool_id: str,
    tool_name: str,
    args: dict,
    turn_id: str = "",
    cancel_event: threading.Event | None = None,
    redirect_event: threading.Event | None = None,
) -> tuple[bool, str | None]:
    """
    Emit an approval_request event and block until approved, denied, or the
    turn is cancelled. Waits indefinitely — there is no timeout.
    Polls every 0.5s so cancel_event/redirect_event are checked promptly.
    Returns (approved, redirect_message). redirect_message is set when the user
    chose "Deny & Redirect" and typed a reason/suggestion.
    """
    ev = threading.Event()
    _pending_approvals[sid] = {"event": ev, "approved": None, "redirect_message": None, "turn_id": turn_id}
    _emit_and_log(session_id, "approval_request", {"id": tool_id, "tool_name": tool_name, "args": args, "turn_id": turn_id})

    while True:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break
        if redirect_event is not None and redirect_event.is_set():
            break

    entry = _pending_approvals.pop(sid, {})

    if cancel_event is not None and cancel_event.is_set():
        return False, None

    if redirect_event is not None and redirect_event.is_set():
        return False, None

    return bool(entry.get("approved", False)), entry.get("redirect_message")


# ---------------------------------------------------------------------------
# report_impossible redirect gate
# ---------------------------------------------------------------------------

# Maps socket session ID to pending redirect state
_pending_impossible_redirects: dict[str, dict] = {}

def _request_impossible_redirect(
    sid: str,
    session_id: str,
    reason: str,
    turn_id: str,
    cancel_event: threading.Event | None,
    redirect_event: threading.Event | None = None,
) -> str | None:
    """
    Emit report_impossible_request and block until the user responds or the
    turn is cancelled.  Waits indefinitely — there is no timeout.  Polls every
    0.5 s so cancel_event/redirect_event are checked promptly.
    Returns redirect_message (str) if the user chose to redirect the LLM, or
    None if they chose "Truly Impossible" / cancelled.
    If redirect_event fires, the stored redirect message is used as the redirect
    guidance (stop-and-redirect resolves the impossible dialog automatically).
    """
    ev = threading.Event()
    _pending_impossible_redirects[sid] = {
        "event": ev, "redirect_message": None, "turn_id": turn_id,
    }
    _emit_and_log(session_id, "report_impossible_request", {
        "reason": reason, "turn_id": turn_id,
    })

    while True:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break
        if redirect_event is not None and redirect_event.is_set():
            break

    entry = _pending_impossible_redirects.pop(sid, {})

    if cancel_event is not None and cancel_event.is_set():
        return None

    if redirect_event is not None and redirect_event.is_set():
        return _redirect_messages.get(session_id) or None

    return entry.get("redirect_message") or None


# ---------------------------------------------------------------------------
# ask_human gate
# ---------------------------------------------------------------------------

# Maps session_id to pending human input state (keyed by session_id, not sid,
# because the tool only has access to session_id via special_resources)
_pending_human_inputs: dict[str, dict] = {}

def _request_human_input(
    session_id: str,
    question: str,
    turn_id: str,
    cancel_event: threading.Event | None,
    redirect_event: threading.Event | None = None,
) -> str | None:
    """
    Emit ask_human_request and block until the user answers or the turn is
    cancelled.  Waits indefinitely — there is no timeout.  Polls every 0.5 s
    so cancel_event/redirect_event are checked promptly.
    Returns the user's answer string, or None on cancel.
    If redirect_event fires, returns the redirect message as the "answer" so
    the LLM sees the guidance in tool results.
    """
    ev = threading.Event()
    _pending_human_inputs[session_id] = {
        "event": ev, "answer": None, "turn_id": turn_id,
    }
    _emit_and_log(session_id, "ask_human_request", {
        "question": question, "turn_id": turn_id,
    })

    while True:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break
        if redirect_event is not None and redirect_event.is_set():
            break

    entry = _pending_human_inputs.pop(session_id, {})

    if cancel_event is not None and cancel_event.is_set():
        return None

    if redirect_event is not None and redirect_event.is_set():
        msg = _redirect_messages.get(session_id, "")
        return f"(User interrupted this question with guidance: {msg})" if msg else None

    return entry.get("answer")


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

_redis_client: redis.Redis | None = None

def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=get_service_port("redis", 6379),
            decode_responses=True,
        )
    return _redis_client


_SESSION_TTL = 3600


def _load_session(session_id: str) -> Session:
    r = _get_redis()
    raw = r.get(f"session:{session_id}")
    if raw:
        try:
            d = json.loads(raw)
            if d.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
                # Schema mismatch — start fresh
                session = Session(session_id=session_id)
            else:
                session = session_from_dict(d)
        except Exception:
            session = Session(session_id=session_id)
    else:
        session = Session(session_id=session_id)

    mem_hash_key = f"session:{session_id}:memory"

    def _on_memory_change(key: str, event_type: str) -> None:
        try:
            keys = r.hkeys(mem_hash_key)
            socketio.emit("session_memory_keys_update", {"keys": keys}, room=session_id)
            socketio.emit("session_memory_key_event", {"key": key, "type": event_type}, room=session_id)
        except Exception as exc:
            logger.warning("_on_memory_change error (key=%r, session_id=%r): %s", key, session_id, exc)

    session.session_data["memory"] = RedisDict(r, mem_hash_key, on_change=_on_memory_change)
    _init_session_caches(session, session_id)
    return session


def _save_session(session_id: str, session: Session) -> None:
    r = _get_redis()
    blob = session_to_dict(session)
    r.setex(f"session:{session_id}", _SESSION_TTL, json.dumps(blob))
    r.expire(f"session:{session_id}:memory", _SESSION_TTL)
    r.expire(f"session:{session_id}:events", _SESSION_TTL)


def _delete_session(session_id: str) -> None:
    """Delete all data for a session from Redis and in-memory caches."""
    r = _get_redis()
    r.delete(f"session:{session_id}")
    r.delete(f"session:{session_id}:memory")
    r.delete(f"session:{session_id}:events")
    _session_tool_sets.pop(session_id, None)
    _session_system_prompts.pop(session_id, None)
    _session_skill_registries.pop(session_id, None)
    _session_project_config.pop(session_id, None)
    _session_current_cwd.pop(session_id, None)
    _session_trace_buffers.pop(session_id, None)
    _redirect_events.pop(session_id, None)
    _redirect_messages.pop(session_id, None)


def clear_all_sessions_on_startup() -> None:
    """Delete every session:* key from Redis at server startup to avoid stale data."""
    try:
        r = _get_redis()
        keys = list(r.scan_iter("session:*"))
        if keys:
            r.delete(*keys)
            logger.info("Cleared %s stale session key(s) from Redis.", len(keys))
        else:
            logger.info("No stale sessions to clear.")
    except Exception as exc:
        logger.warning("Could not clear sessions on startup: %s", exc)


# ---------------------------------------------------------------------------
# HTTP API — session creation
# ---------------------------------------------------------------------------

@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    """
    Create a new session with per-session context.
    Body (JSON):
      initial_cwd                   str   — working directory for this session
      pin_project_memory            bool  — pin project memory to initial_cwd (default true)
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
    pin_project_memory = bool(data.get("pin_project_memory", True))
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
            return jsonify({"error": f"startup_tool_calls.json not found at {startup_tool_calls_path!r}"}), 400
        except Exception as exc:
            return jsonify({"error": f"Failed to load startup_tool_calls.json: {exc}"}), 400

    session = Session(
        session_id=session_id,
        initial_cwd=initial_cwd,
        pin_project_memory=pin_project_memory,
        skills_path=skills_path,
        custom_tools_path=custom_tools_path,
        startup_tool_calls=startup_tool_calls,
        interim_response_as_thinking=interim_response_as_thinking,
        record_traces=record_traces,
    )

    if record_traces:
        _session_trace_buffers[session_id] = deque()

    # Pre-validate and cache custom tools so errors surface at creation time.
    if custom_tools_path:
        try:
            extra_defs, extra_map, plugins = load_custom_tools(
                tools_dir=custom_tools_path,
                workspace_root=initial_cwd or None,
                session_prefix=session_id[:8],
            )
            _session_tool_sets[session_id] = (
                list(ALL_TOOL_DEFINITIONS) + extra_defs,
                {**_TOOL_MAP, **extra_map},
                plugins,
            )
        except RuntimeError as exc:
            return jsonify({"error": f"Custom tool loading failed: {exc}"}), 400
    else:
        _session_tool_sets[session_id] = (ALL_TOOL_DEFINITIONS, _TOOL_MAP, [])

    _session_system_prompts[session_id] = build_system_prompt(
        starting_environment_info=_build_starting_environment_info(session),
    )
    registry = build_skill_registry(custom_skills_path=skills_path)
    _session_skill_registries[session_id] = registry
    session.session_data["__skill_files__"] = registry
    _session_project_config[session_id] = {
        "initial_cwd": initial_cwd,
        "pin_project_memory": pin_project_memory,
    }
    _session_current_cwd[session_id] = initial_cwd

    _save_session(session_id, session)

    logger.info("Session created: %s cwd=%r", session_id, initial_cwd)
    return jsonify({"session_id": session_id})


@app.route("/api/sessions", methods=["GET"])
def api_list_sessions():
    """
    List all persisted sessions with lightweight metadata.
    Returns a JSON array sorted by created_at descending.
    """
    r = _get_redis()
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
        # Collect task titles from completed turns (most recent last → display newest at top)
        task_titles = [
            t["task_title"] for t in completed_turns
            if t.get("task_title")
        ]
        if current_turn and current_turn.get("task_title"):
            task_titles.append(current_turn["task_title"])
        results.append({
            "session_id": session_id,
            "initial_cwd": d.get("initial_cwd", ""),
            "current_cwd": _session_current_cwd.get(session_id) or d.get("initial_cwd", ""),
            "created_at": d.get("created_at", 0.0),
            "turn_count": turn_count,
            "active_turn": session_id in _session_active_turns,
            "task_titles": task_titles,
            "interim_response_as_thinking": d.get("interim_response_as_thinking", False),
            "record_traces": d.get("record_traces", False),
            "pin_project_memory": d.get("pin_project_memory", True),
            "skills_path": d.get("skills_path") or None,
            "custom_tools_path": d.get("custom_tools_path") or None,
        })
    results.sort(key=lambda s: s["created_at"], reverse=True)
    return jsonify(results)


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def api_delete_session(session_id: str):
    """Delete all data for a session from Redis and in-memory caches."""
    if session_id in _session_active_turns:
        return jsonify({"error": "Cannot delete a session with an active turn"}), 409
    _delete_session(session_id)
    logger.info("Session deleted via API: %s", session_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Session defaults — single source of truth for new-session option defaults.
# Hardcoded values are used unless a DB param overrides them.
# Add new DB-driven defaults here; the frontend and CLI both read this.
# ---------------------------------------------------------------------------

_SESSION_DEFAULTS_HARDCODED: dict = {
    "pin_project_memory":           False,
    "interim_response_as_thinking": False,
    "record_traces":                False,
    "load_skills":                  False,
    "load_tools":                   False,
    "load_startup_tool_calls":      False,
}

# Maps DB param key (as stored in kv_store) -> session defaults key
_SESSION_DEFAULTS_FROM_DB: dict[str, str] = {
    "params.model.default_irat": "interim_response_as_thinking",
}


@app.route("/api/session-defaults", methods=["GET"])
def api_session_defaults():
    """Return default values for all new-session options."""
    defaults = dict(_SESSION_DEFAULTS_HARDCODED)
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            for param_key, defaults_key in _SESSION_DEFAULTS_FROM_DB.items():
                val = kv.get_value(param_key)
                if val is not None:
                    defaults[defaults_key] = val
    except Exception as exc:
        return jsonify({"error": f"Failed to load session defaults from database: {exc}"}), 500
    return jsonify(defaults)


@app.route("/api/system-info", methods=["GET"])
def api_system_info():
    """Return basic system information useful for the dashboard."""
    return jsonify({
        "home_dir": str(pathlib.Path.home()).replace("\\", "/"),
        "workspace_dir": get_default_workspace_dir(),
    })


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


# ---------------------------------------------------------------------------
# LLM config loader
# ---------------------------------------------------------------------------

def _load_llm_config() -> dict | None:
    """Return dict with endpoint_url, token_value, model or None on failure."""
    return load_llm_config()


# ---------------------------------------------------------------------------
# Message sanitization
# ---------------------------------------------------------------------------

# Keys that are part of the OpenAI chat-completion message spec.
# Internal control keys (e.g. agentic_loop_control_type) are stripped here
# before any payload is sent to the LLM.
_OPENAI_MESSAGE_KEYS: frozenset[str] = frozenset(
    {"role", "content", "tool_calls", "tool_call_id", "name"}
)


def sanitize_messages_for_llm(messages: list[dict]) -> list[dict]:
    """Return a new list with all non-OpenAI-spec keys removed from every message."""
    return [
        {k: v for k, v in msg.items() if k in _OPENAI_MESSAGE_KEYS}
        for msg in messages
    ]


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------

def _build_llm_payload(session: Session, current_turn: Turn) -> list[dict]:
    """Assemble the message list actually sent to the LLM endpoint."""
    messages: list[dict] = [{"role": "system", "content": _get_session_system_prompt(session.session_id)}]
    for turn in session.completed_turns:
        messages.append({"role": "user", "content": turn.condensed_user})
        messages.append({"role": "assistant", "content": turn.condensed_assistant})
    messages.extend(current_turn.to_messages())
    return messages


# ---------------------------------------------------------------------------
# Context-limit / timeout detection helpers
# ---------------------------------------------------------------------------

_CONTEXT_LIMIT_KEYWORDS = (
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "maximum token",
    "context window",
    "too many tokens",
    "input is too long",
    "prompt is too long",
    "exceeds the maximum",
)


def _is_context_limit_error(exc: Exception) -> bool:
    try:
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        response = exc.response
        if response is None:
            return False
        if response.status_code not in (400, 413, 422):
            return False
        body = response.text.lower()
        return any(kw in body for kw in _CONTEXT_LIMIT_KEYWORDS)
    except Exception:
        return False


def _is_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.TimeoutException)


def _is_retryable_error(exc: Exception) -> bool:
    return _is_context_limit_error(exc) or _is_timeout_error(exc)


# ---------------------------------------------------------------------------
# Async LLM call abstraction
# ---------------------------------------------------------------------------

async def _async_run_llm_call(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    exchange_idx: int,
    tool_defs: list[dict] | None = None,
    interim_response_as_thinking: bool = False,
    record: bool = False,
) -> tuple[object, str, str]:
    """
    Run one async LLM call (streaming) and emit token events.
    Returns (result, content_for_history, reasoning_accumulated).
    Raises on HTTP/network errors. Immediately cancellable via asyncio task cancellation.
    When interim_response_as_thinking=True, content tokens are emitted as type "reasoning"
    so the frontend displays them in the thinking panel instead of counting chars.
    When record=True, the completed TraceEntry is appended to the session trace buffer.
    """
    acc: dict[str, str] = {"content": "", "reasoning": ""}
    token_count = 0

    def on_data(chunk: dict) -> None:
        nonlocal token_count
        if chunk.get("reasoning"):
            acc["reasoning"] += chunk["reasoning"]
            socketio.emit("token", {
                "type": "reasoning", "text": chunk["reasoning"],
                "turn_id": turn_id,
            }, room=session_id)
        if chunk.get("content"):
            acc["content"] += chunk["content"]
            emit_type = "reasoning" if interim_response_as_thinking else "content"
            socketio.emit("token", {
                "type": emit_type, "text": chunk["content"],
                "turn_id": turn_id,
            }, room=session_id)
            token_count += 1
            if token_count % 50 == 0:
                _emit_content_snapshot(session_id, turn_id, exchange_idx, acc["content"], acc["reasoning"])

    result = await streaming_llm.stream(
        sanitize_messages_for_llm(payload), on_data,
        tools=(tool_defs if tool_defs is not None else ALL_TOOL_DEFINITIONS),
        record=record,
    )
    _emit_content_snapshot(session_id, turn_id, exchange_idx, acc["content"], acc["reasoning"])

    if result.trace is not None:
        result.trace.turn_id = turn_id
        result.trace.exchange_idx = exchange_idx
        buf = _session_trace_buffers.get(session_id)
        if buf is not None:
            buf.append(result.trace)

    return result, acc["content"], acc["reasoning"]


def _emit_content_snapshot(
    session_id: str, turn_id: str, exchange_idx: int,
    assistant_content: str, reasoning: str,
) -> None:
    """Emit a replay_content_snapshot event (logged to Redis Streams for replay)."""
    _emit_and_log(session_id, "replay_content_snapshot", {
        "turn_id": turn_id,
        "exchange_idx": exchange_idx,
        "assistant_content": assistant_content,
        "reasoning": reasoning,
    })


# ---------------------------------------------------------------------------
# Async retry wrapper
# ---------------------------------------------------------------------------

async def _async_run_llm_call_with_retry(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    exchange_idx: int,
    assistant_truncation_chars: int | None = None,
    tool_defs: list[dict] | None = None,
    tool_map: dict | None = None,
    interim_response_as_thinking: bool = False,
    record: bool = False,
) -> tuple[object, str, str]:
    """
    Run an async LLM call; on timeout or context-limit error, strip the payload
    and retry once.
    Returns (result, content_for_history, reasoning).
    Each attempt (original and retry) produces its own TraceEntry if record=True.
    """
    try:
        return await _async_run_llm_call(streaming_llm, payload, session_id, turn_id, exchange_idx, tool_defs, interim_response_as_thinking, record=record)
    except Exception as exc:
        if not _is_retryable_error(exc):
            raise

        reason = "timeout" if _is_timeout_error(exc) else "context limit exceeded"
        _emit_backend_log(
            session_id,
            colored(f"LLM call failed ({reason}), retrying with stripped context…", "yellow")
        )

        actual_tool_map = tool_map if tool_map is not None else _TOOL_MAP
        stripped = strip_down_messages(
            payload, actual_tool_map,
            assistant_truncation_chars=assistant_truncation_chars,
        )
        return await _async_run_llm_call(streaming_llm, stripped, session_id, turn_id, exchange_idx, tool_defs, interim_response_as_thinking, record=record)


# ---------------------------------------------------------------------------
# Trace save helpers
# ---------------------------------------------------------------------------

def _build_traces_xml(session_id: str, entries: list) -> str:
    """Serialize a list of TraceEntry objects to an XML string."""
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone

    root = ET.Element("traces")
    root.set("session_id", session_id)
    root.set("saved_at", datetime.now(timezone.utc).isoformat())

    for entry in entries:
        trace_el = ET.SubElement(root, "trace")
        trace_el.set("turn_id", entry.turn_id)
        trace_el.set("exchange_idx", str(entry.exchange_idx))
        trace_el.set("captured_at", str(entry.captured_at))

        req_el = ET.SubElement(trace_el, "request")
        # Store the full request payload as JSON — includes model, messages, tools,
        # temperature, and any other params that were sent to the endpoint.
        req_el.text = json.dumps(entry.request_payload, ensure_ascii=False)

        resp_el = ET.SubElement(trace_el, "response")
        ET.SubElement(resp_el, "content").text = entry.content
        ET.SubElement(resp_el, "reasoning").text = entry.reasoning

        tcs_el = ET.SubElement(resp_el, "tool_calls")
        for tc in entry.tool_calls:
            tc_el = ET.SubElement(tcs_el, "tool_call")
            tc_el.set("id", tc.id)
            tc_el.set("name", tc.name)
            ET.SubElement(tc_el, "arguments").text = json.dumps(tc.arguments, ensure_ascii=False)

        if entry.usage is not None:
            ET.SubElement(resp_el, "usage").text = json.dumps(entry.usage, ensure_ascii=False)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def _rotate_traces_folder() -> None:
    """Delete oldest trace files until the folder is within _trace_folder_max_bytes."""
    if _trace_folder_max_bytes is None:
        return
    from pathlib import Path
    files = sorted(
        Path(_traces_dir).glob("*.xml"),
        key=lambda p: p.stat().st_mtime,
    )
    total = sum(f.stat().st_size for f in files)
    while total > _trace_folder_max_bytes and files:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _stub_tool_result(full_result: str, max_chars: int, session_data: dict) -> str:
    import secrets
    memory = session_data.get("memory", {})
    while True:
        code = secrets.token_hex(4)
        key = f"stubs.{code}"
        if key not in memory:
            break
    memory[key] = full_result
    total = len(full_result)
    overflow = total - max_chars
    preview = full_result[:max_chars]
    return (
        f"** STUBBED LONG RETURN VALUE **\n"
        f"(total {total} chars, session_memory_key=\"{key}\")\n"
        f"Preview:\n\n"
        f"{preview}... (+ {overflow} more chars)"
    )


def _execute_tools(
    result: Any,
    content_for_history: str,
    session: Session,
    sid: str,
    session_id: str,
    current_turn: Turn,
    return_value_max_chars: int | None = None,
    cancel_event: threading.Event | None = None,
    tool_map: dict | None = None,
    redirect_event: threading.Event | None = None,
) -> tuple[bool, str | None, LLMExchange]:
    """
    Execute all tool calls in result, emit events, and build an LLMExchange record.
    Returns (was_impossible, reason_or_none, exchange).
    Always pops _report_impossible from session_data before returning.
    """
    turn_id = current_turn.id
    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, session_id),
        "on_log": lambda msg: _emit_backend_log(session_id, msg),
        "session_id": session_id,
        "initial_cwd": session.initial_cwd,
        "cancel_event": cancel_event,
        "ask_human_fn": lambda q: _request_human_input(
            session_id, q, turn_id, cancel_event, redirect_event=redirect_event
        ),
    }

    actual_tool_map = tool_map if tool_map is not None else _TOOL_MAP
    if _hotfix_bad_parser:
        for tc in result.tool_calls:
            if "<|channel|>" in tc.name:
                clean = tc.name.split("<|channel|>")[0]
                if clean in actual_tool_map:
                    tc.name = clean
    if _hotfix_void_call:
        for tc in result.tool_calls:
            module = actual_tool_map.get(tc.name)
            if module is not None:
                props = getattr(module, "DEFINITION", {}).get("function", {}).get("parameters", {}).get("properties")
                if not props and tc.arguments:
                    tc.arguments = {}

    exchange = LLMExchange(
        assistant_content=content_for_history,
        is_final=False,
    )

    was_impossible = False
    reason: str | None = None

    try:
        for tc in result.tool_calls:
            # Check redirect before starting each tool; caller will inject guidance.
            if redirect_event is not None and redirect_event.is_set():
                return False, None, exchange

            _emit_and_log(session_id, "tool_call", {
                "id": tc.id, "name": tc.name, "args": tc.arguments,
                "turn_id": turn_id,
            })

            tool_record = ToolCallRecord(id=tc.id, name=tc.name, args=tc.arguments)

            if check_needs_approval(tc.name, tc.arguments, tool_map=actual_tool_map):
                approved, redirect_message = _request_approval(
                    sid, session_id, tc.id, tc.name, tc.arguments,
                    turn_id=turn_id, cancel_event=cancel_event,
                    redirect_event=redirect_event,
                )
                if not approved:
                    # If cancelled or redirected, return early — caller handles it.
                    if cancel_event is not None and cancel_event.is_set():
                        exchange.tool_calls.append(tool_record)
                        return False, None, exchange
                    if redirect_event is not None and redirect_event.is_set():
                        return False, None, exchange

                    if redirect_message:
                        denial = (
                            f"Error: NOT Approved. User did not approve this action. "
                            f"User suggests: {redirect_message}"
                        )
                    else:
                        denial = "Error: NOT Approved. User did not approve this action."

                    tool_record.result = denial
                    exchange.tool_calls.append(tool_record)
                    # Human authored this denial — preserve the exchange verbatim so
                    # compaction never overwrites the exact reason with a vague summary.
                    exchange.has_human_content = True
                    _emit_and_log(session_id, "tool_result", {
                        "id": tc.id, "result": denial, "turn_id": turn_id,
                    })
                    continue  # Let the LLM see the denial and decide how to proceed

            # Inject streaming callback into special_resources if the tool supports it
            module = actual_tool_map.get(tc.name)
            if getattr(module, "STREAMS_RESULT", False):
                _tc_id = tc.id
                def _on_chunk(chunk: str, _id: str = _tc_id) -> None:
                    socketio.emit("tool_result_chunk", {
                        "id": _id, "chunk": chunk, "turn_id": turn_id,
                    }, room=session_id)
                special_resources["on_chunk"] = _on_chunk
            else:
                special_resources.pop("on_chunk", None)

            started_at = int(time.time() * 1000)
            tool_record.started_at = started_at
            _emit_and_log(session_id, "tool_call_start", {
                "id": tc.id, "turn_id": turn_id, "started_at": started_at,
            })

            session.session_data["__pinned_project__"] = session.initial_cwd if session.pin_project_memory else None
            try:
                tool_result = execute_tool(tc.name, tc.arguments, session.session_data, special_resources, tool_map=actual_tool_map)
            except ToolHangError as e:
                tool_result = f"HANG: {e}"
            except ToolTimeoutError as e:
                tool_result = f"TIMEOUT: {e}"

            finished_at = int(time.time() * 1000)
            tool_record.finished_at = finished_at
            special_resources.pop("on_chunk", None)

            if return_value_max_chars is not None and len(tool_result) > return_value_max_chars:
                tool_result = _stub_tool_result(tool_result, return_value_max_chars, session.session_data)
                tool_record.was_stubbed = True

            tool_record.result = tool_result
            exchange.tool_calls.append(tool_record)

            # ask_human result is authored by the human — never compress it.
            # (Distinguish real answers from the canned "user did not respond" message.)
            if tc.name == "ask_human" and tool_result and not tool_result.startswith(
                "The user did not respond"
            ):
                exchange.has_human_content = True

            _emit_and_log(session_id, "tool_result", {
                "id": tc.id, "result": tool_result, "turn_id": turn_id,
                "started_at": started_at, "finished_at": finished_at,
            })
            if tc.name == "change_pwd":
                _session_current_cwd[session_id] = os.getcwd()
                _emit_and_log(session_id, "pwd_update", {"path": os.getcwd().replace("\\", "/")})
            if tc.name == "todo_list":
                _raw = session.session_data.get("todo_list") or []
                _emit_and_log(session_id, "todo_list_update", {
                    "items": _todo_format_items_for_ui(_raw), "turn_id": turn_id,
                })

            # Check redirect after tool completes; return partial exchange — caller injects guidance.
            if redirect_event is not None and redirect_event.is_set():
                return False, None, exchange

        if session.session_data.get("_report_impossible"):
            reason = session.session_data.get("_report_impossible")
            was_impossible = True

        return was_impossible, reason, exchange

    finally:
        session.session_data.pop("_report_impossible", None)


# ---------------------------------------------------------------------------
# Todo list helpers
# ---------------------------------------------------------------------------

def _get_closed_items(todo_list: list) -> list[str]:
    return [it["text"] for it in todo_list if it.get("status") == "closed"]


def _get_open_items(todo_list: list) -> list[str]:
    result = []
    for item in todo_list:
        sub = item.get("sub_list")
        if sub is not None:
            # promoted sub-list parent — recurse; counts as open if any child is open
            result.extend(_get_open_items(sub))
        elif item.get("status") != "closed":
            result.append(item["text"])
    return result


# ---------------------------------------------------------------------------
# Early compaction helpers
# ---------------------------------------------------------------------------

# Skip compaction when the total chars of the exchanges to compact is below this
# threshold.  Prevents unnecessary LLM calls when only a small amount of context
# has accumulated (e.g. two or three quick todo closures in rapid succession).
MIN_COMPACTION_CHARS = 8192

# Maximum display length for LLM-generated task titles.  Titles that exceed this
# (e.g. from thinking models that output reasoning before the short title) are
# truncated with an ellipsis before being stored and emitted.
TITLE_MAX_CHARS = 80


def _exchange_chars(exchange: LLMExchange) -> int:
    """Return a rough char count of the significant content in an exchange."""
    total = len(exchange.assistant_content or "")
    for tc in exchange.tool_calls:
        total += len(tc.result or "")
    total += len(exchange.user_continuation or "")
    return total


def _closed_items_from_exchange(exchange: LLMExchange) -> list[tuple[str, str]]:
    """
    Return a list of (item_path, display_message) for every todo item that was
    successfully closed in this exchange batch.

    Handles both close_item (single) and close_many_items (batch).
    Any result that does not parse or lacks the expected shape is ignored.
    """
    closed: list[tuple[str, str]] = []
    for tc in exchange.tool_calls:
        if tc.name != "todo_list":
            continue
        action = tc.args.get("action")
        result_str = tc.result or ""
        try:
            result_json = json.loads(result_str)
        except (json.JSONDecodeError, ValueError):
            continue

        if action == "close_item":
            if result_json.get("status") == "closed":
                item_path = result_json.get("item_path") or tc.args.get("item_path", "?")
                message = result_json.get("message") or f"Closed item '{item_path}'"
                closed.append((item_path, message))

        elif action == "close_many_items":
            for entry in result_json.get("closed") or []:
                item_path = entry.get("item_path", "?")
                message = entry.get("message") or f"Closed item '{item_path}'"
                closed.append((item_path, message))

    return closed


def _split_compactable_segments(
    exchanges: list[LLMExchange],
    indices: list[int],
) -> list[list[int]]:
    """
    Split a list of exchange indices into contiguous sub-lists that exclude any
    exchange tagged with has_human_content=True.

    Human-content exchanges (approval denials, ask_human answers, report_impossible
    redirects) are kept raw — they are never included in any CompactionRecord so
    the LLM always sees exact human instructions verbatim rather than a lossy summary.

    Example: indices [0,1,2,3,4] where exchanges 1 and 3 have human content →
      returns [[0], [2], [4]]  (three separate compactable segments)
    """
    segments: list[list[int]] = []
    current: list[int] = []
    for idx in indices:
        if exchanges[idx].has_human_content:
            if current:
                segments.append(current)
                current = []
            # Human-content exchange: skip (always kept raw)
        else:
            current.append(idx)
    if current:
        segments.append(current)
    return segments


async def _compact_exchanges(
    streaming_llm: StreamingLLM,
    exchanges: list[LLMExchange],
    max_tokens: int | None = None,
) -> str | None:
    """
    Make a non-streaming LLM call to summarise a sequence of exchanges.
    Returns the summary text, or None if the call fails or returns nothing useful.

    The payload is a plain-text transcript (system + user) built by
    build_compaction_messages — no tool-call wire format, so the compaction
    model cannot echo function-call syntax into the summary.
    """
    compaction_messages = build_compaction_messages(exchanges)

    try:
        fetch_result = await asyncio.to_thread(
            streaming_llm.fetch, compaction_messages, max_tokens,
        )
        text = (fetch_result.content or "").strip()
        return text or None
    except Exception as exc:
        logger.warning("Compaction LLM call failed: %s", exc)
        return None


async def _fetch_task_title(
    streaming_llm: StreamingLLM,
    user_text: str,
    max_tokens: int | None,
) -> str | None:
    """
    Make a non-streaming LLM call to generate a short title for the task.
    Returns the title string (truncated to TITLE_MAX_CHARS), or None on failure.

    max_tokens follows the same fallback pattern as watchdog_max_tokens: when set
    it caps the token budget; when None the model default is used.  TITLE_MAX_CHARS
    provides a hard display truncation for thinking-model overflow.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a labelling assistant. "
                "Given a user request, output a short title of 3-7 words that captures "
                "the essence of what the user wants to accomplish. "
                "Output ONLY the title — no punctuation, no quotes, no explanation."
            ),
        },
        {"role": "user", "content": user_text},
    ]
    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, max_tokens)
        title = (result.content or "").strip()
        if not title:
            return None
        if len(title) > TITLE_MAX_CHARS:
            title = title[:TITLE_MAX_CHARS - 1] + "…"
        return title
    except Exception as exc:
        logger.warning("Task title LLM call failed: %s", exc)
        return None


def _truncate_watchdog_text(text: Any, max_chars: int) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    if len(text) <= max_chars:
        return text
    overflow = len(text) - max_chars
    return text[:max_chars] + f"... ({overflow} more chars)"


def _messages_to_watchdog_transcript(messages: list[dict]) -> str:
    """Render stripped messages into plain text for the final-answer watchdog."""
    lines: list[str] = []
    for idx, msg in enumerate(messages, start=1):
        role = msg.get("role", "?")
        lines.append(f"[Message {idx}] {role.upper()}")

        content = _truncate_watchdog_text(msg.get("content") or "", 700).strip()
        if content:
            lines.append(content)

        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                name = tc.get("function", {}).get("name", "")
                args = _truncate_watchdog_text(tc.get("function", {}).get("arguments", "") or "", 400)
                lines.append(f"Tool Call: {name}")
                if args:
                    lines.append(f"Args: {args}")
        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id:
                lines.append(f"Tool Call ID: {tc_id}")

        lines.append("")

    return "\n".join(lines).strip()


async def _is_sufficient_final_answer(
    streaming_llm: StreamingLLM,
    session: Session,
    current_turn: Turn,
    candidate_text: str,
    assistant_truncation_chars: int | None,
    tool_map: dict,
    watchdog_max_tokens: int | None,
) -> bool:
    """
    Ask a small out-of-band evaluator whether candidate_text already serves as a
    sufficient direct answer or final summary for the current turn.
    """
    payload = _build_llm_payload(session, current_turn)
    stripped = strip_down_messages(
        payload,
        tool_map,
        assistant_truncation_chars=assistant_truncation_chars,
    )
    transcript = _messages_to_watchdog_transcript(stripped)

    todo_list = session.session_data.get("todo_list") or []
    open_items = _get_open_items(todo_list)
    closed_items = _get_closed_items(todo_list)
    todo_status = (
        f"todo_items_created={len(todo_list)}, "
        f"todo_items_closed={len(closed_items)}, "
        f"todo_items_open={len(open_items)}"
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are evaluating whether an assistant's latest reply is already sufficient to end "
                "a tool-assisted turn.\n"
                "\n"
                "Reply with exactly one word: YES or NO.\n"
                "\n"
                "Reply YES if the latest reply already functions as either:\n"
                "  - a direct final answer to a simple request, or\n"
                "  - a sufficient final summary/answer after tool use.\n"
                "\n"
                "Reply NO if the latest reply is only a partial status update, weak closing remark, "
                "reasoning fragment, or otherwise fails to clearly answer/summarize the work."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{current_turn.user_text}\n\n"
                f"Turn facts:\n"
                f"- had_tool_calls: {current_turn.count_tool_calls() > 0}\n"
                f"- {todo_status}\n\n"
                f"Prior conversation transcript (already stripped/truncated for evaluator use):\n"
                f"{transcript or '(empty)'}\n\n"
                f"Latest assistant reply to evaluate:\n{candidate_text}"
            ),
        },
    ]
    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, watchdog_max_tokens)
        decision = (result.content or "").strip().upper()
        return decision == "YES"
    except Exception as exc:
        logger.warning("Final-answer watchdog LLM call failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Async agent loop
# ---------------------------------------------------------------------------

async def _redirect_watcher_coro(
    redirect_event: threading.Event,
    target_task: asyncio.Task,
) -> None:
    """Poll redirect_event every 0.3 s and cancel target_task when it fires."""
    while not redirect_event.is_set():
        await asyncio.sleep(0.3)
    target_task.cancel()


async def _async_agent_loop(
    sid: str,
    session_id: str,
    session: Session,
    streaming_llm: StreamingLLM,
    turn_id: str,
    current_turn: Turn,
    return_value_max_chars: int | None,
    assistant_truncation_chars: int | None,
    cancel_event: threading.Event,
    compaction_max_tokens: int | None = None,
    watchdog_max_tokens: int | None = None,
    redirect_event: threading.Event | None = None,
) -> None:
    """
    Main agentic loop. Runs inside a private asyncio event loop in the SocketIO thread.
    LLM calls are async (httpx) — immediately cancellable via asyncio task cancellation.
    Tool calls run in a thread pool (asyncio.to_thread) so the event loop stays responsive.
    """
    had_tool_calls = False
    # One-shot latch: after we inject the explicit final-summary continuation,
    # the next no-tool response is accepted as final.
    final_summary_reprompt_sent = False
    was_impossible = False
    impossible_reason: str | None = None
    was_cancelled = False
    last_assistant_content = ""
    turn_completed = False

    session_tool_defs = _get_session_tool_defs(session_id)
    session_tool_map = _get_session_tool_map(session_id)

    try:
        while True:
            if cancel_event.is_set():
                was_cancelled = True
                break

            is_interim_call = had_tool_calls and not final_summary_reprompt_sent
            if is_interim_call:
                _emit_and_log(session_id, "begin_interim_stream", {
                    "turn_id": turn_id,
                    "show_char_count": not session.interim_response_as_thinking,
                })

            exchange_idx = len(current_turn.exchanges)
            payload = _build_llm_payload(session, current_turn)

            # Run LLM call with a redirect watcher that cancels this task when
            # redirect_event fires, allowing us to inject the guidance message.
            _watcher = (
                asyncio.create_task(_redirect_watcher_coro(redirect_event, asyncio.current_task()))
                if redirect_event is not None else None
            )
            _llm_redirected = False
            try:
                result, content_for_history, reasoning = await _async_run_llm_call_with_retry(
                    streaming_llm, payload,
                    session_id=session_id,
                    turn_id=turn_id,
                    exchange_idx=exchange_idx,
                    assistant_truncation_chars=assistant_truncation_chars,
                    tool_defs=session_tool_defs,
                    tool_map=session_tool_map,
                    interim_response_as_thinking=session.interim_response_as_thinking and is_interim_call,
                    record=session.record_traces,
                )
            except asyncio.CancelledError:
                if redirect_event is not None and redirect_event.is_set() and not cancel_event.is_set():
                    _llm_redirected = True
                else:
                    was_cancelled = True
                    if _watcher is not None:
                        _watcher.cancel()
                    raise
            except httpx.HTTPStatusError as exc:
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                _emit_and_log(session_id, "error", {
                    "message": f"LLM stream error:\n\n{format_http_error(exc)}",
                    "turn_id": turn_id,
                })
                break
            except Exception as exc:
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                _emit_and_log(session_id, "error", {
                    "message": f"LLM stream error:\n\n{exc}",
                    "turn_id": turn_id,
                })
                break
            finally:
                if _watcher is not None:
                    _watcher.cancel()

            if _llm_redirected:
                redirect_msg = _redirect_messages.pop(session_id, "User interrupted.")
                if redirect_event is not None:
                    redirect_event.clear()
                redir_ex = LLMExchange(assistant_content="", is_final=False)
                redir_ex.user_continuation = (
                    f"User interrupted you, and gave the following guidance: {redirect_msg}"
                )
                redir_ex.has_human_content = True
                had_tool_calls = True
                current_turn.exchanges.append(redir_ex)
                _save_session(session_id, session)
                continue

            usage = getattr(result, "usage", None)
            if usage:
                _emit_backend_log(
                    session_id,
                    colored("Usage: ", "cyan") +
                    f"prompt={usage.get('prompt_tokens', '?')}, "
                    f"completion={usage.get('completion_tokens', '?')}, "
                    f"total={usage.get('total_tokens', '?')}"
                )

            last_assistant_content = content_for_history

            if cancel_event.is_set():
                was_cancelled = True
                break

            if result.has_tool_calls:
                try:
                    impossible, reason, exchange = await asyncio.to_thread(
                        _execute_tools,
                        result, content_for_history, session, sid, session_id,
                        current_turn, return_value_max_chars, cancel_event,
                        session_tool_map, redirect_event,
                    )
                except asyncio.CancelledError:
                    cancel_event.set()
                    was_cancelled = True
                    raise

                exchange.reasoning = reasoning
                had_tool_calls = True
                current_turn.exchanges.append(exchange)
                # Save in-progress turn state to Redis after each tool batch
                _save_session(session_id, session)

                # Check cancel first — cancel takes priority over redirect.
                if cancel_event.is_set():
                    was_cancelled = True
                    break

                # Check redirect: _execute_tools returned early; inject guidance and continue.
                if redirect_event is not None and redirect_event.is_set():
                    redirect_msg = _redirect_messages.pop(session_id, "User interrupted.")
                    redirect_event.clear()
                    exchange.user_continuation = (
                        f"User interrupted you, and gave the following guidance: {redirect_msg}"
                    )
                    exchange.has_human_content = True
                    _save_session(session_id, session)
                    continue

                # Pre-compaction: if this exchange is about to trigger an impossible
                # redirect dialog, tag it NOW so the compaction logic below will not
                # include it in any CompactionRecord.  The redirect (human-authored
                # guidance) will be injected as user_continuation after compaction runs.
                if impossible:
                    exchange.has_human_content = True

                # Early compaction: if any todo item was just closed, compact exchanges
                # since the last compaction.  Human-content exchanges (approvals, ask_human
                # answers, impossible redirects) are excluded from compaction and always kept
                # verbatim — the range is split into disjoint compactable segments around them.
                # exchange_idx of the newly appended exchange = len(exchanges) - 1.
                closed_items = _closed_items_from_exchange(exchange)
                if closed_items:
                    last_covered_idx = max(
                        (max(cr.covers_exchange_indices) for cr in current_turn.compaction_records),
                        default=-1,
                    )
                    # new_indices covers from right after the last compacted exchange
                    # up to and including the just-appended exchange.
                    new_indices = list(range(last_covered_idx + 1, len(current_turn.exchanges)))
                    total_chars = sum(
                        _exchange_chars(current_turn.exchanges[i]) for i in new_indices
                    )
                    if new_indices and total_chars >= MIN_COMPACTION_CHARS:
                        item_label = ", ".join(path for path, _ in closed_items)
                        # Split into contiguous compactable segments, skipping any exchange
                        # that has human-authored content so it stays verbatim in context.
                        segments = _split_compactable_segments(current_turn.exchanges, new_indices)
                        compacted_any = False
                        for segment in segments:
                            if not segment:
                                continue
                            _emit_and_log(session_id, "compaction_start", {
                                "turn_id": turn_id,
                                "exchange_indices": segment,
                                "item_label": item_label,
                            })
                            seg_exchanges = [current_turn.exchanges[i] for i in segment]
                            summary = await _compact_exchanges(
                                streaming_llm, seg_exchanges, max_tokens=compaction_max_tokens,
                            )
                            if summary:
                                cr = CompactionRecord(
                                    summary_text=summary,
                                    covers_exchange_indices=segment,
                                )
                                current_turn.compaction_records.append(cr)
                                _emit_and_log(session_id, "compaction_done", {
                                    "turn_id": turn_id,
                                    "summary_text": summary,
                                    "item_label": item_label,
                                })
                                compacted_any = True
                            else:
                                _emit_backend_log(
                                    session_id,
                                    colored("Compaction LLM call failed for a segment, continuing without summary.", "yellow"),
                                )
                        if compacted_any:
                            human_count = sum(
                                1 for i in new_indices
                                if current_turn.exchanges[i].has_human_content
                            )
                            note = (
                                f" ({human_count} human-content exchange(s) preserved verbatim)"
                                if human_count else ""
                            )
                            _emit_backend_log(
                                session_id,
                                colored(
                                    f"[compaction] Compacted {len(segments)} segment(s) "
                                    f"({len(new_indices) - human_count} exchanges) "
                                    f"after closing: {item_label}{note}",
                                    "magenta",
                                ),
                            )
                        _save_session(session_id, session)

                if impossible:
                    redirect = _request_impossible_redirect(
                        sid, session_id, reason, turn_id, cancel_event,
                        redirect_event=redirect_event,
                    )
                    if redirect_event is not None and redirect_event.is_set():
                        redirect_event.clear()
                        _redirect_messages.pop(session_id, None)
                    if redirect:
                        # User chose to redirect — inject guidance and continue the loop.
                        # exchange is already appended above; mutate it in place.
                        exchange.user_continuation = (
                            f"The user thinks your task is possible if you do the following: "
                            f"{redirect}"
                        )
                        _save_session(session_id, session)
                        continue
                    # User confirmed truly impossible (or timed out / cancelled).
                    was_impossible = True
                    impossible_reason = reason
                    _emit_and_log(session_id, "report_impossible", {
                        "reason": reason, "turn_id": turn_id,
                    })
                    _emit_and_log(session_id, "message_done", {
                        "content": None, "turn_id": turn_id,
                    })
                    turn_completed = True
                    break

                continue

            # No tool calls — this is a non-tool assistant response.
            # Check for unclosed todos.
            unclosed = _get_open_items(session.session_data.get("todo_list") or [])
            if unclosed:
                items_text = "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(unclosed))
                continuation = f"You still have {len(unclosed)} unclosed todo item(s). Please continue:\n{items_text}"
                interim_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=False,
                    user_continuation=continuation,
                )
                current_turn.exchanges.append(interim_exchange)
                _save_session(session_id, session)
                continue

            if had_tool_calls and not final_summary_reprompt_sent:
                has_content = bool(content_for_history and content_for_history.strip())
                is_sufficient = False
                if has_content:
                    is_sufficient = await _is_sufficient_final_answer(
                        streaming_llm,
                        session,
                        current_turn,
                        content_for_history,
                        assistant_truncation_chars,
                        session_tool_map,
                        watchdog_max_tokens,
                    )

                if is_sufficient:
                    # Latest no-tool response already serves as the final answer/summary.
                    final_exchange = LLMExchange(
                        assistant_content=content_for_history,
                        reasoning=reasoning,
                        is_final=True,
                    )
                    current_turn.exchanges.append(final_exchange)
                    _emit_and_log(session_id, "message_done", {
                        "content": content_for_history, "turn_id": turn_id,
                    })
                    turn_completed = True
                    break
                final_summary_reprompt_sent = True
                continuation = (
                    "All action items are complete. "
                    "Please provide your final summary or answer based on the steps "
                    "you took, the tool results, and the previous context."
                )
                interim_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=False,
                    user_continuation=continuation,
                )
                current_turn.exchanges.append(interim_exchange)
                _emit_and_log(session_id, "final_reprompt", {"turn_id": turn_id})
                _emit_and_log(session_id, "begin_final_summary", {"turn_id": turn_id})
                _save_session(session_id, session)
                continue

            # Final response
            final_exchange = LLMExchange(
                assistant_content=content_for_history,
                reasoning=reasoning,
                is_final=True,
            )
            current_turn.exchanges.append(final_exchange)
            _emit_and_log(session_id, "message_done", {
                "content": content_for_history, "turn_id": turn_id,
            })
            turn_completed = True
            break

    except asyncio.CancelledError:
        was_cancelled = True
        raise
    finally:
        # Always runs: finalize turn and save session regardless of exit path.
        if was_cancelled:
            current_turn.was_cancelled = True
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(session.session_data.get("todo_list") or [])
            current_turn.finalize(session.session_data, last_assistant_content)
            session.completed_turns.append(current_turn)
            session.current_turn = None
            _emit_and_log(session_id, "turn_cancelled", {"turn_id": turn_id})
            _emit_and_log(session_id, "message_done", {"content": None, "turn_id": turn_id})
        elif turn_completed:
            current_turn.was_impossible = was_impossible
            current_turn.impossible_reason = impossible_reason
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(session.session_data.get("todo_list") or [])
            current_turn.finalize(session.session_data, last_assistant_content)
            session.completed_turns.append(current_turn)
            session.current_turn = None

        _save_session(session_id, session)


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

    # Warn if another SID is already active for this session (multi-tab not supported).
    existing = [s for s, sess in _sid_to_session_id.items() if sess == session_id and s != sid]
    if existing:
        logger.warning(
            "Session %s already has active SID(s) %s. New SID %s also joining. Multi-tab is not supported.",
            session_id,
            existing,
            sid,
        )

    logger.info("Client connected: %s -> session %s", sid, session_id)
    _sid_to_session_id[sid] = session_id
    join_room(session_id)


@socketio.on("resume_session")
def handle_resume_session(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return

    last_event_id = data.get("lastEventId", "0-0")
    session = _load_session(session_id)

    # Emit startup log after session is loaded
    skills_path = session.skills_path
    if skills_path:
        try:
            _skills_count = len([f for f in os.listdir(skills_path) if f.lower().endswith(".md")])
            skills_str = f"enabled ({_skills_count} files)"
        except OSError:
            skills_str = "enabled (path error)"
    else:
        skills_str = "disabled"
    _effective_initial_cwd = session.initial_cwd or "(none)"
    _emit_backend_log(
        session_id,
        colored("System started", "green") +
        f": streaming=True, skills={skills_str}, os={_env_os}, shell={_env_shell}, "
        f"initial_cwd={_effective_initial_cwd!r}"
    )

    if session.schema_version != CURRENT_SCHEMA_VERSION:
        emit("session_state", {"schemaInvalid": True})
        return

    completed_turns_data = [turn_to_dict(t) for t in session.completed_turns]
    current_turn_data = turn_to_dict(session.current_turn) if session.current_turn else None
    is_turn_active = session_id in _cancel_tasks
    emit("session_state", {
        "startupDone": session.startup_done,
        "completedTurns": completed_turns_data,
        "currentTurn": current_turn_data,
        "isTurnActive": is_turn_active,
    })

    # Always emit event_replay (even if empty) — frontend uses it as the "restore done" signal.
    try:
        r = _get_redis()
        events = get_events_since(r, session_id, last_event_id)
    except Exception as exc:
        logger.warning("Event replay error for session %s: %s", session_id, exc)
        events = []
    emit("event_replay", {"events": events, "replay_complete": True})

    # If a host_shell command is currently running, emit a full output snapshot so the
    # frontend can restore the streaming shell output without gaps.
    try:
        from src.tools.host_shell import get_active_output
        snapshot = get_active_output(session_id)
        if snapshot is not None:
            emit("shell_output_snapshot", {"output": snapshot})
    except Exception as exc:
        logger.warning("shell_output_snapshot error for session %s: %s", session_id, exc)


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    session_id = _sid_to_session_id.pop(sid, None)
    logger.info("Client disconnected: %s (session=%s)", sid, session_id)
    # Release any pending approval for this SID
    pending = _pending_approvals.pop(sid, None)
    if pending and not pending["event"].is_set():
        pending["approved"] = False
        pending["event"].set()
    # Do NOT delete the session — it persists for reconnect


@socketio.on("cancel_turn")
def handle_cancel_turn():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    loop = _cancel_loops.get(session_id)
    task = _cancel_tasks.get(session_id)
    if loop is not None and task is not None:
        loop.call_soon_threadsafe(task.cancel)
    logger.info("Cancel requested for session %s", session_id)


@socketio.on("stop_and_redirect")
def handle_stop_and_redirect(data):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    message = (data or {}).get("message", "User interrupted turn, please try again.")
    _redirect_messages[session_id] = message
    ev = _redirect_events.get(session_id)
    if ev is not None:
        ev.set()
    # Wake up any pending blocking waits so they check redirect_event promptly.
    pending_approval = _pending_approvals.get(sid)
    if pending_approval:
        pending_approval["event"].set()
    pending_human = _pending_human_inputs.get(session_id)
    if pending_human:
        pending_human["event"].set()
    pending_redirect = _pending_impossible_redirects.get(sid)
    if pending_redirect:
        pending_redirect["event"].set()
    logger.info("Stop-and-redirect for session %s: %r", session_id, message)


@socketio.on("get_pwd")
def handle_get_pwd():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    cwd = _session_current_cwd.get(session_id) or os.getcwd()
    socketio.emit("pwd_update", {"path": cwd.replace("\\", "/")}, room=session_id)


@socketio.on("get_skills_info")
def handle_get_skills_info():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    session = _load_session(session_id)
    skills_path = session.skills_path
    if skills_path:
        try:
            skills_files = sorted(f for f in os.listdir(skills_path) if f.lower().endswith(".md"))
        except OSError:
            skills_files = []
        socketio.emit("skills_info", {
            "enabled": True, "count": len(skills_files),
            "path": skills_path.replace("\\", "/"), "files": skills_files,
        }, room=session_id)
    else:
        socketio.emit("skills_info", {
            "enabled": False, "count": 0, "path": None, "files": [],
        }, room=session_id)


@socketio.on("get_system_prompt")
def handle_get_system_prompt():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    socketio.emit("system_prompt", {"text": _get_session_system_prompt(session_id)}, room=session_id)


@socketio.on("get_env_info")
def handle_get_env_info():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    cfg = _session_project_config.get(session_id, {})
    socketio.emit("env_info", {
        "os": _env_os, "shell": _env_shell,
        "initialCwd": cfg.get("initial_cwd", ""),
    }, room=session_id)


@socketio.on("get_session_memory_keys")
def handle_get_session_memory_keys():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    keys = _get_redis().hkeys(f"session:{session_id}:memory")
    socketio.emit("session_memory_keys_update", {"keys": keys}, room=session_id)


@socketio.on("get_session_memory_value")
def handle_get_session_memory_value(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    key = data.get("key", "")
    value = _get_redis().hget(f"session:{session_id}:memory", key)
    if value is not None:
        socketio.emit("session_memory_value", {"key": key, "value": value, "found": True}, room=session_id)
    else:
        socketio.emit("session_memory_value", {"key": key, "value": "", "found": False}, room=session_id)


@socketio.on("get_project_memory_keys")
def handle_get_project_memory_keys():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    project = _get_default_project(session_id)
    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn).list_keys(project=project)
    socketio.emit("project_memory_keys_update", {"keys": keys}, room=session_id)


@socketio.on("get_project_memory_value")
def handle_get_project_memory_value(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    key = data.get("key", "")
    project = _get_default_project(session_id)
    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)
    if value is not None:
        value_str = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
        socketio.emit("project_memory_value", {"key": key, "value": value_str, "found": True}, room=session_id)
    else:
        socketio.emit("project_memory_value", {"key": key, "value": "", "found": False}, room=session_id)


@socketio.on("get_tools_info")
def handle_get_tools_info():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    tool_defs = _get_session_tool_defs(session_id)
    plugins = _get_session_plugins(session_id)
    total = len(tool_defs)
    custom_count = sum(p["count"] for p in plugins)
    socketio.emit("tools_info", {
        "totalCount": total,
        "builtinCount": total - custom_count,
        "builtinPath": "src/tools/",
        "names": [d["function"]["name"] for d in tool_defs],
        "customPlugins": plugins if plugins else None,
    }, room=session_id)


@socketio.on("approval_response")
def handle_approval_response(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    tool_id = data.get("id")
    approved = bool(data.get("approved"))
    pending = _pending_approvals.get(sid)
    if pending:
        pending["approved"] = approved
        pending["redirect_message"] = data.get("redirect_message") or None
        _emit_and_log(session_id, "approval_resolved", {"id": tool_id, "approved": approved, "turn_id": pending.get("turn_id", "")})
        pending["event"].set()


@socketio.on("impossible_redirect_response")
def handle_impossible_redirect_response(data: dict):
    sid = request.sid
    pending = _pending_impossible_redirects.get(sid)
    if pending:
        pending["redirect_message"] = data.get("redirect_message") or None
        pending["event"].set()


@socketio.on("ask_human_response")
def handle_ask_human_response(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    pending = _pending_human_inputs.get(session_id)
    if pending:
        pending["answer"] = data.get("answer") or ""
        _emit_and_log(session_id, "ask_human_resolved", {
            "answer": pending["answer"], "turn_id": pending.get("turn_id", ""),
        })
        pending["event"].set()


@socketio.on("save_traces")
def handle_save_traces():
    """Flush the session trace buffer to an XML file in _traces_dir."""
    from datetime import datetime, timezone
    import uuid as _uuid

    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        emit("traces_saved", {"count": 0, "filename": None})
        return

    buf = _session_trace_buffers.get(session_id)
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
        os.makedirs(_traces_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        short_id = str(_uuid.uuid4())[:8]
        filename = f"{timestamp}_{short_id}.xml"
        filepath = os.path.join(_traces_dir, filename)

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
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        emit("startup_tool_calls_done", {"count": 0})
        return

    session = _load_session(session_id)

    if not session.startup_tool_calls:
        socketio.emit("startup_tool_calls_done", {"count": 0}, room=session_id)
        return

    if session.startup_done:
        socketio.emit("startup_tool_calls_done", {"count": 0, "skipped": True}, room=session_id)
        return

    # Navigate to session's CWD before running startup tool calls.
    _startup_cwd = _session_current_cwd.get(session_id) or session.initial_cwd
    if _startup_cwd:
        try:
            os.chdir(_startup_cwd)
        except OSError as _chdir_err:
            socketio.emit("backend_log", {"text": f"Warning: could not chdir to {_startup_cwd!r}: {_chdir_err}"}, room=session_id)

    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, session_id),
        "on_log": lambda msg: _emit_backend_log(session_id, msg),
        "initial_cwd": session.initial_cwd,
    }
    startup_tool_map = _get_session_tool_map(session_id)

    for i, tc_spec in enumerate(session.startup_tool_calls):
        name = tc_spec.get("name", "")
        args = tc_spec.get("args", {})
        tc_id = f"startup-{i}"

        socketio.emit("startup_tool_call", {"id": tc_id, "name": name, "args": args}, room=session_id)

        session.session_data["__pinned_project__"] = session.initial_cwd if session.pin_project_memory else None
        try:
            result = execute_tool(name, args, session.session_data, special_resources, tool_map=startup_tool_map)
        except Exception as exc:
            result = f"Error executing '{name}': {exc}"

        socketio.emit("startup_tool_result", {"id": tc_id, "result": result}, room=session_id)

        if name == "change_pwd":
            _session_current_cwd[session_id] = os.getcwd()
            socketio.emit("pwd_update", {"path": os.getcwd().replace("\\", "/")}, room=session_id)

    session.startup_done = True
    _save_session(session_id, session)
    socketio.emit("startup_tool_calls_done", {"count": len(session.startup_tool_calls)}, room=session_id)


@socketio.on("user_message")
def handle_user_message(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    # Guard against submitting a new turn while one is already active.
    if session_id in _cancel_tasks:
        emit("error", {"message": "A turn is already in progress. Please wait or cancel first."})
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    turn_id: str = data.get("clientTurnId") or ""
    if not turn_id:
        turn_id = str(_uuid_module.uuid4())

    llm_config = _load_llm_config()
    if llm_config is None:
        _emit_and_log(session_id, "error", {
            "message": "No active token/endpoint configured. Run `slbp token use` first.",
            "turn_id": turn_id,
        })
        return

    streaming_llm = StreamingLLM(
        llm_config["endpoint_url"],
        llm_config["token_value"],
        60,
        llm_config["model"],
        llm_config["model_params"],
    )
    return_value_max_chars: int | None = llm_config["system_params"].get("return_value_max_chars")
    assistant_truncation_chars: int | None = llm_config["system_params"].get("assistant_strip_truncation_chars")
    compaction_max_tokens: int | None = llm_config["system_params"].get("compaction_max_tokens")
    watchdog_max_tokens: int | None = llm_config["system_params"].get("watchdog_max_tokens")
    title_summary_max_tokens: int | None = llm_config["system_params"].get("title_summary_max_tokens")

    session = _load_session(session_id)
    session.session_data["todo_list"] = []
    _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})

    # Navigate to this session's current working directory before the turn runs.
    # _session_current_cwd tracks navigations across turns; falls back to initial_cwd.
    _effective_cwd = _session_current_cwd.get(session_id) or session.initial_cwd
    if _effective_cwd:
        try:
            os.chdir(_effective_cwd)
        except OSError as _chdir_err:
            _emit_backend_log(session_id, f"Warning: could not chdir to {_effective_cwd!r}: {_chdir_err}")

    user_text_with_context = text
    current_turn = Turn(
        id=turn_id,
        user_text=text,
        user_text_with_context=user_text_with_context,
    )
    session.current_turn = current_turn

    _emit_and_log(session_id, "turn_start", {"turn_id": turn_id, "user_text": text})

    # Create threading.Events for subprocess tools and a private asyncio event loop
    # for real httpx-level LLM cancellation.
    cancel_event = threading.Event()
    redirect_event = threading.Event()
    _redirect_events[session_id] = redirect_event

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _cancel_loops[session_id] = loop

    async def _fetch_and_store_title() -> None:
        """Fire-and-forget: fetch a short title and emit it to the frontend."""
        title = await _fetch_task_title(streaming_llm, text, title_summary_max_tokens)
        if title:
            current_turn.task_title = title
            _emit_and_log(session_id, "task_title", {"turn_id": turn_id, "title": title})
            _save_session(session_id, session)

    async def _run() -> None:
        task = asyncio.current_task()
        _cancel_tasks[session_id] = task
        try:
            # Fire title fetch concurrently — it resolves independently of the agent loop.
            asyncio.create_task(_fetch_and_store_title())
            await _async_agent_loop(
                sid, session_id, session, streaming_llm,
                turn_id, current_turn,
                return_value_max_chars, assistant_truncation_chars,
                cancel_event,
                compaction_max_tokens=compaction_max_tokens,
                watchdog_max_tokens=watchdog_max_tokens,
                redirect_event=redirect_event,
            )
        except asyncio.CancelledError:
            # cancel_event already set inside _async_agent_loop's finally
            cancel_event.set()
        finally:
            _cancel_tasks.pop(session_id, None)
            _cancel_loops.pop(session_id, None)

    _session_active_turns.add(session_id)
    try:
        loop.run_until_complete(_run())
    finally:
        _session_active_turns.discard(session_id)
        _redirect_events.pop(session_id, None)
        _redirect_messages.pop(session_id, None)
        loop.close()
