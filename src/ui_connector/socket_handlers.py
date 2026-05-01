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
from src.logic.system_prompt import (
    SkillManifestError,
    build_system_prompt,
    build_skill_registry,
    build_injected_skills_section,
    get_autoload_skill_entries,
    get_selector_candidate_entries,
    resolve_skill_dependency_closure,
)
from src.utils.emitting_kv_manager import EmittingKVManager
from src.utils.redis_dict import RedisDict
from src.utils.request_error_formatting import format_http_error
from src.utils.env_info import format_environment_info, get_default_workspace_dir, get_os, get_shell
from src.utils.session_model import (
    Session, Turn, Subturn, LLMExchange, ToolCallRecord,
    session_to_dict, session_from_dict, turn_to_dict, turn_from_dict,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.event_log import log_event, get_events_since, REPLAY_EXCLUDED_EVENTS
from src.utils.exceptions import ToolHangError, ToolTimeoutError
from src.utils.docker_compose import get_service_port
from termcolor import colored

logger = logging.getLogger(__name__)

_BASE_SKILL_REGISTRY: list[dict] = build_skill_registry()
_BASE_SYSTEM_PROMPT: str = build_system_prompt(
    autoload_entries=get_autoload_skill_entries(_BASE_SKILL_REGISTRY),
)

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
# session_id -> list of skill descriptors {id, name, blurb, filename, path, source, dependencies, autoload}
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


def _get_session_skill_registry(session_id: str) -> list[dict]:
    return _session_skill_registries.get(session_id, _BASE_SKILL_REGISTRY)


def _get_autoloaded_session_skills(session_id: str) -> list[dict]:
    return get_autoload_skill_entries(_get_session_skill_registry(session_id))


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

    if session_id not in _session_skill_registries:
        registry = build_skill_registry(custom_skills_path=session.skills_path)
        _session_skill_registries[session_id] = registry
        session.session_data["__skill_files__"] = registry
    else:
        registry = _session_skill_registries[session_id]
        session.session_data["__skill_files__"] = registry

    if session_id not in _session_system_prompts:
        autoload_entries = get_autoload_skill_entries(registry)
        _session_system_prompts[session_id] = build_system_prompt(
            starting_environment_info=_build_starting_environment_info(session),
            autoload_entries=autoload_entries,
        )

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
# Two-phase: soft_interrupt fires redirect_event immediately (on button click);
# stop_and_redirect delivers the message (on "Send").  The loop waits for the
# message before injecting guidance.  Unlike cancel_event, this does not end the turn.
_redirect_events: dict[str, threading.Event] = {}
_redirect_messages: dict[str, str] = {}
_redirect_message_ready: dict[str, threading.Event] = {}  # set when message arrives after soft_interrupt


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
    _redirect_message_ready.pop(session_id, None)


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

    try:
        registry = build_skill_registry(custom_skills_path=skills_path)
    except SkillManifestError as exc:
        return jsonify({"error": f"Skill loading failed: {exc}"}), 400
    _session_skill_registries[session_id] = registry
    session.session_data["__skill_files__"] = registry
    _session_system_prompts[session_id] = build_system_prompt(
        starting_environment_info=_build_starting_environment_info(session),
        autoload_entries=get_autoload_skill_entries(registry),
    )
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

def _build_llm_payload(
    session: Session,
    current_turn: Turn,
    skills_section: str | None = None,
) -> list[dict]:
    """Assemble the message list actually sent to the LLM endpoint.

    Completed subturns (from prior turns and prior subturns of the current turn) are
    injected as compacted user/assistant pairs using their detailed_summary when available.
    Only the live (last) subturn of current_turn uses full exchange messages.
    """
    system_content = _get_session_system_prompt(session.session_id)
    if skills_section:
        system_content = system_content + "\n" + skills_section
    messages: list[dict] = [{"role": "system", "content": system_content}]

    # Completed turns: inject each subturn as a compacted user/assistant pair
    for turn in session.completed_turns:
        for subturn in turn.subturns:
            messages.append({"role": "user", "content": subturn.user_text_with_context})
            messages.append({"role": "assistant", "content": _subturn_assistant_context(subturn)})

    # Current turn: prior subturns as compacted pairs, live subturn as full messages
    prior_subturns = current_turn.subturns[:-1]
    live_subturn = current_turn.subturns[-1] if current_turn.subturns else None

    for subturn in prior_subturns:
        messages.append({"role": "user", "content": subturn.user_text_with_context})
        messages.append({"role": "assistant", "content": _subturn_assistant_context(subturn)})

    if live_subturn:
        messages.append({"role": "user", "content": live_subturn.user_text_with_context})
        for exchange in live_subturn.exchanges:
            messages.extend(exchange.to_messages())

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


# ---------------------------------------------------------------------------
# Async LLM call abstraction
# ---------------------------------------------------------------------------

async def _async_run_llm_call(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    subturn_id: str,
    exchange_idx: int,
    tool_defs: list[dict] | None = None,
    suppress_content_streaming: bool = False,
    record: bool = False,
) -> tuple[object, str, str]:
    """
    Run one async LLM call (streaming) and emit token events.
    Returns (result, content_for_history, reasoning_accumulated).
    Raises on HTTP/network errors. Immediately cancellable via asyncio task cancellation.
    When suppress_content_streaming=True, content tokens are NOT emitted during streaming
    (they still accumulate for return); caller flushes them later via irat_thinking_flush.
    True reasoning tokens (response.reasoning) are always emitted immediately.
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
            if not suppress_content_streaming:
                socketio.emit("token", {
                    "type": "content", "text": chunk["content"],
                    "turn_id": turn_id,
                }, room=session_id)
            token_count += 1
            if token_count % 50 == 0:
                _emit_content_snapshot(session_id, turn_id, subturn_id, exchange_idx, acc["content"], acc["reasoning"])

    result = await streaming_llm.stream(
        sanitize_messages_for_llm(payload), on_data,
        tools=(tool_defs if tool_defs is not None else ALL_TOOL_DEFINITIONS),
        record=record,
    )
    _emit_content_snapshot(session_id, turn_id, subturn_id, exchange_idx, acc["content"], acc["reasoning"])

    if result.trace is not None:
        result.trace.turn_id = turn_id
        result.trace.exchange_idx = exchange_idx
        buf = _session_trace_buffers.get(session_id)
        if buf is not None:
            buf.append(result.trace)

    return result, acc["content"], acc["reasoning"]


def _emit_content_snapshot(
    session_id: str, turn_id: str, subturn_id: str, exchange_idx: int,
    assistant_content: str, reasoning: str,
) -> None:
    """Emit a replay_content_snapshot event (logged to Redis Streams for replay)."""
    _emit_and_log(session_id, "replay_content_snapshot", {
        "turn_id": turn_id,
        "subturn_id": subturn_id,
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
    subturn_id: str,
    exchange_idx: int,
    tool_defs: list[dict] | None = None,
    suppress_content_streaming: bool = False,
    record: bool = False,
) -> tuple[object, str, str]:
    """
    Run an async LLM call; surfaces a user-friendly error on context-limit.
    Returns (result, content_for_history, reasoning).
    """
    try:
        return await _async_run_llm_call(streaming_llm, payload, session_id, turn_id, subturn_id, exchange_idx, tool_defs, suppress_content_streaming, record=record)
    except Exception as exc:
        if _is_context_limit_error(exc):
            raise RuntimeError(
                "Context limit exceeded — the conversation is too long for the model's context window.\n"
                "Please start a new session or shorten the conversation."
            ) from exc
        raise


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
) -> LLMExchange:
    """
    Execute all tool calls in result, emit events, and build an LLMExchange record.
    Returns the exchange.
    """
    turn_id = current_turn.id
    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, session_id),
        "on_log": lambda msg: _emit_backend_log(session_id, msg),
        "session_id": session_id,
        "initial_cwd": session.initial_cwd,
        "cancel_event": cancel_event,
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

    try:
        for tc in result.tool_calls:
            # Check redirect before starting each tool; caller will inject guidance.
            if redirect_event is not None and redirect_event.is_set():
                return exchange

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
                        return exchange
                    if redirect_event is not None and redirect_event.is_set():
                        return exchange

                    if redirect_message:
                        denial = (
                            f"Error: NOT Approved. User did not approve this action. "
                            f"User suggests: {redirect_message}"
                        )
                    else:
                        denial = "Error: NOT Approved. User did not approve this action."

                    tool_record.result = denial
                    exchange.tool_calls.append(tool_record)
                    _emit_and_log(session_id, "tool_result", {
                        "id": tc.id, "result": denial, "turn_id": turn_id,
                    })
                    continue  # Let the LLM see the denial and decide how to proceed

            # Always inject on_chunk so any tool can emit progress updates.
            _tc_id = tc.id
            def _on_chunk(chunk: str, _id: str = _tc_id) -> None:
                socketio.emit("tool_result_chunk", {
                    "id": _id, "chunk": chunk, "turn_id": turn_id,
                }, room=session_id)
            special_resources["on_chunk"] = _on_chunk

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

            _tool_module = actual_tool_map.get(tc.name)
            _no_stub = getattr(_tool_module, "NO_STUB", False)
            if not _no_stub and return_value_max_chars is not None and len(tool_result) > return_value_max_chars:
                tool_result = _stub_tool_result(tool_result, return_value_max_chars, session.session_data)
                tool_record.was_stubbed = True

            tool_record.result = tool_result
            exchange.tool_calls.append(tool_record)

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
                return exchange

        return exchange

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
# ---------------------------------------------------------------------------
# Task title helpers
# ---------------------------------------------------------------------------

# Maximum display length for LLM-generated task titles.  Titles that exceed this
# (e.g. from thinking models that output reasoning before the short title) are
# truncated with an ellipsis before being stored and emitted.
TITLE_MAX_CHARS = 80


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
    current_subturn: Subturn,
    candidate_text: str,
    watchdog_max_tokens: int | None,
) -> bool:
    """
    Ask a small out-of-band evaluator whether candidate_text is a sufficient final answer,
    question, or impossibility statement for the current subturn.
    Scoped to the current subturn's request — uses full turn payload only as context.
    """
    payload = _build_llm_payload(session, current_turn)
    transcript = _messages_to_watchdog_transcript(payload)

    todo_list = session.session_data.get("todo_list") or []
    open_items = _get_open_items(todo_list)
    closed_items = _get_closed_items(todo_list)
    todo_status = (
        f"todo_items_created={len(todo_list)}, "
        f"todo_items_closed={len(closed_items)}, "
        f"todo_items_open={len(open_items)}"
    )
    subturn_had_tool_calls = current_subturn.count_tool_calls() > 0

    messages = [
        {
            "role": "system",
            "content": (
                "You are evaluating whether an assistant's latest reply is a valid final response "
                "that ends the current subturn.\n"
                "\n"
                "Reply with exactly one word: YES or NO.\n"
                "\n"
                "Reply YES if the latest reply is any of the following:\n"
                "  - A direct final answer or summary of completed work.\n"
                "  - A question or request for clarification directed at the user.\n"
                "  - A statement that the task cannot be completed, with a clear explanation.\n"
                "\n"
                "Reply NO if the reply is only a partial status update, reasoning fragment, "
                "or interim step that does not resolve the subturn."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{current_subturn.user_text}\n\n"
                f"Turn facts:\n"
                f"- had_tool_calls: {subturn_had_tool_calls}\n"
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


def _subturn_final_response(subturn: Subturn) -> str:
    """Extract just the final response text from a subturn (stripping Context Details if present)."""
    if subturn.detailed_summary:
        marker = "\nContext Details:"
        idx = subturn.detailed_summary.find(marker)
        if idx >= 0:
            return subturn.detailed_summary[:idx].strip()
        return subturn.detailed_summary.strip()
    for ex in reversed(subturn.exchanges):
        if ex.is_final:
            return ex.assistant_content
    if subturn.exchanges:
        return subturn.exchanges[-1].assistant_content
    return ""


def _subturn_assistant_context(subturn: Subturn) -> str:
    """Return the full context string for a completed subturn (compaction if available, else final response)."""
    if subturn.detailed_summary:
        return subturn.detailed_summary
    for ex in reversed(subturn.exchanges):
        if ex.is_final:
            return ex.assistant_content
    if subturn.exchanges:
        return subturn.exchanges[-1].assistant_content
    return ""


def _format_tool_calls_for_compaction(subturn: Subturn) -> str:
    """Format all tool calls in a subturn into a readable string for the compaction prompt."""
    MAX_ARG_CHARS = 300
    MAX_RESULT_CHARS = 500
    lines: list[str] = []
    for ex in subturn.exchanges:
        for tc in ex.tool_calls:
            args_str = json.dumps(tc.args, ensure_ascii=False)
            if len(args_str) > MAX_ARG_CHARS:
                args_str = args_str[:MAX_ARG_CHARS] + "..."
            result_str = tc.result or "(no result)"
            if len(result_str) > MAX_RESULT_CHARS:
                result_str = result_str[:MAX_RESULT_CHARS] + "..."
            lines.append(f"{tc.name}({args_str})")
            lines.append(f"  Result: {result_str}")
    return "\n".join(lines)


def _compute_subturn_compaction(
    streaming_llm: StreamingLLM,
    subturn: Subturn,
    final_content: str,
) -> str:
    """Synchronous: call LLM to produce a detailed compaction for a completed subturn."""
    tool_calls_text = _format_tool_calls_for_compaction(subturn)
    messages = [
        {
            "role": "system",
            "content": (
                "You are writing a context summary of an AI agent's completed work unit.\n"
                "Output EXACTLY this format, nothing else:\n\n"
                "{verbatim final response}\n\n"
                "Context Details:\n"
                "Tools used:\n"
                "- {tool_name}: {one-sentence: why called and what it accomplished}\n"
                "Memory changes:\n"
                "- {key or path}: {one-sentence: what was stored and why}\n\n"
                "Rules:\n"
                "- Copy the final response EXACTLY as provided — do not alter it\n"
                "- List every tool call under 'Tools used:'\n"
                "- Under 'Memory changes:' list only session_memory and project_memory writes; "
                "if none, write a single line: (none)\n"
                "- One bullet per item, one sentence each\n"
                "- Output nothing else"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Final response (copy verbatim):\n{final_content}\n\n"
                f"Tool calls made:\n{tool_calls_text}"
            ),
        },
    ]
    try:
        result = streaming_llm.fetch(messages)
        text = (result.content or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("Subturn compaction LLM call failed: %s", exc)
    return f"{final_content}\n\nContext Details:\n(summary unavailable)"


async def _generate_and_store_compaction(
    streaming_llm: StreamingLLM,
    session_id: str,
    turn_id: str,
    current_subturn: Subturn,
    final_content: str,
) -> None:
    """Async: generate a compaction for a completed subturn, store it, and emit to frontend."""
    compaction = await asyncio.to_thread(
        _compute_subturn_compaction, streaming_llm, current_subturn, final_content
    )
    current_subturn.detailed_summary = compaction
    _emit_and_log(session_id, "subturn_compaction", {
        "turn_id": turn_id,
        "subturn_id": current_subturn.id,
        "compaction": compaction,
    })


async def _is_continuation(
    streaming_llm: StreamingLLM,
    session: Session,
    user_text: str,
    watchdog_max_tokens: int | None,
) -> bool:
    """
    Decide whether a new user message is a follow-up continuation of the previous turn
    or an entirely new independent request.  Leans toward continuation: ambiguous cases
    return True.
    """
    last_turn = session.completed_turns[-1]
    last_subturn = last_turn.subturns[-1] if last_turn.subturns else None
    if last_subturn:
        last_response = _subturn_final_response(last_subturn)
    else:
        last_response = last_turn.condensed_assistant or ""

    messages = [
        {
            "role": "system",
            "content": (
                "You are deciding whether a new user message is an entirely new, independent task "
                "or a continuation of the previous conversation.\n"
                "Reply with exactly one word: YES or NO.\n"
                "YES = the message is a completely new, unrelated task that has nothing to do with "
                "the previous response.\n"
                "NO  = the message continues, extends, questions, or builds on the previous response.\n"
                "When in doubt, reply NO."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Previous assistant response:\n{last_response}\n\n"
                f"New user message:\n{user_text}"
            ),
        },
    ]
    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, watchdog_max_tokens)
        decision = (result.content or "").strip().upper()
        # YES means "new task" → not a continuation; NO means continuation
        return decision != "YES"
    except Exception as exc:
        logger.warning("Continuation watchdog LLM call failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Skill selector watchdog
# ---------------------------------------------------------------------------

_SKILL_SELECTOR_TURN_CHARS = 600  # max chars per turn in the context transcript


def _build_skill_selector_transcript(session: Session) -> str:
    """Format completed turns into a short context transcript for the skill selector."""
    if not session.completed_turns:
        return ""
    lines: list[str] = []
    for i, turn in enumerate(session.completed_turns, start=1):
        user = (turn.condensed_user or "").strip()
        assistant = (turn.condensed_assistant or "").strip()
        if len(user) > _SKILL_SELECTOR_TURN_CHARS:
            user = user[:_SKILL_SELECTOR_TURN_CHARS] + "..."
        if len(assistant) > _SKILL_SELECTOR_TURN_CHARS:
            assistant = assistant[:_SKILL_SELECTOR_TURN_CHARS] + "..."
        lines.append(f"[Turn {i}]")
        lines.append(f"User: {user}")
        lines.append(f"Assistant: {assistant}")
        lines.append("")
    return "\n".join(lines).strip()


async def _select_skills_for_turn(
    streaming_llm: StreamingLLM,
    session: Session,
    user_text: str,
    skill_registry: list[dict],
    watchdog_max_tokens: int | None,
) -> list[dict]:
    """Run a lightweight LLM call to decide which skills to inject for this turn.

    Returns the list of selected skill registry entries (empty if none selected).
    """
    selector_candidates = get_selector_candidate_entries(skill_registry)
    if not selector_candidates:
        return []

    skill_list_lines = [
        f"- {e['id']} -- {e['name']} -- {e['blurb']}" for e in selector_candidates
    ]
    skill_list = "\n".join(skill_list_lines)

    transcript = _build_skill_selector_transcript(session)
    context_block = ""
    if transcript:
        context_block = f"Conversation so far:\n{transcript}\n\n"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a skill selector. Given a conversation transcript and the current "
                "user request, decide which skill guides (if any) should be loaded to help "
                "complete the request.\n\n"
                "Each skill is a specialized guide with instructions for a specific task type.\n\n"
                f"Available skills:\n{skill_list}\n\n"
                "Output ONLY a comma-separated list of skill ids to load, or the single word "
                "'none' if no skills are needed. Return only ids or 'none'."
            ),
        },
        {
            "role": "user",
            "content": f"{context_block}Current request: {user_text}",
        },
    ]

    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, watchdog_max_tokens)
        response = (result.content or "").strip().lower()
        if not response or response == "none":
            return []
        selected_ids = {f.strip() for f in response.split(",") if f.strip()}
        return [e for e in selector_candidates if e["id"] in selected_ids]
    except Exception as exc:
        logger.warning("Skill selector watchdog failed: %s", exc)
        return []


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
    current_subturn: Subturn,
    return_value_max_chars: int | None,
    cancel_event: threading.Event,
    watchdog_max_tokens: int | None = None,
    redirect_event: threading.Event | None = None,
) -> None:
    """
    Main agentic loop. Runs inside a private asyncio event loop in the SocketIO thread.
    LLM calls are async (httpx) — immediately cancellable via asyncio task cancellation.
    Tool calls run in a thread pool (asyncio.to_thread) so the event loop stays responsive.
    Per-subturn state variables are scoped to the current subturn only.
    """
    had_tool_calls = False
    # Latched True the first time any todo item is created during this subturn.
    had_todo_items = False
    # One-shot latch: after we inject the explicit final-summary continuation,
    # the next no-tool response is accepted as final regardless of watchdog result.
    final_summary_reprompt_sent = False
    # Best no-tool response the watchdog rated as a sufficient final answer so far.
    pending_final_candidate: tuple[str, str] | None = None  # (content, reasoning)
    was_cancelled = False
    last_assistant_content = ""
    turn_completed = False


    session_tool_defs = _get_session_tool_defs(session_id)
    session_tool_map = _get_session_tool_map(session_id)

    skill_registry = _get_session_skill_registry(session_id)
    baseline_skills = _get_autoloaded_session_skills(session_id)
    baseline_skill_ids = {entry["id"] for entry in baseline_skills}
    selected_skills = await _select_skills_for_turn(
        streaming_llm, session, current_subturn.user_text, skill_registry, watchdog_max_tokens
    )
    turn_resolved_skills = resolve_skill_dependency_closure(
        skill_registry,
        [entry["id"] for entry in selected_skills],
    )
    turn_only_skills = [
        entry for entry in turn_resolved_skills
        if entry["id"] not in baseline_skill_ids
    ]
    loaded_skills = baseline_skills + turn_only_skills
    if loaded_skills:
        _emit_and_log(session_id, "skills_loaded", {
            "turn_id": turn_id,
            "skill_names": [entry["name"] for entry in loaded_skills],
        })
    active_skills_section = build_injected_skills_section(turn_only_skills) if turn_only_skills else ""

    try:
        while True:
            if cancel_event.is_set():
                was_cancelled = True
                break

            is_interim_call = had_tool_calls and not final_summary_reprompt_sent
            if is_interim_call:
                _emit_and_log(session_id, "begin_interim_stream", {
                    "turn_id": turn_id,
                    # In IRAT mode we suppress content streaming entirely and flush
                    # after the watchdog decides — no char count shown either way.
                    "show_char_count": not session.interim_response_as_thinking,
                })

            exchange_idx = len(current_subturn.exchanges)
            payload = _build_llm_payload(session, current_turn, active_skills_section or None)

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
                    subturn_id=current_subturn.id,
                    exchange_idx=exchange_idx,
                    tool_defs=session_tool_defs,
                    # In IRAT mode, suppress real-time content emission for interim
                    # calls; the caller decides whether to flush via irat_thinking_flush.
                    suppress_content_streaming=session.interim_response_as_thinking and is_interim_call,
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
                # If soft_interrupt fired before the message arrived, wait for it now.
                # CancelledError propagates naturally here if cancel_turn fires.
                _msg_ready = _redirect_message_ready.pop(session_id, None)
                if _msg_ready is not None and not _redirect_messages.get(session_id):
                    while not _msg_ready.is_set():
                        await asyncio.sleep(0.1)
                redirect_msg = _redirect_messages.pop(session_id, "User interrupted.")
                if redirect_event is not None:
                    redirect_event.clear()
                redir_ex = LLMExchange(assistant_content="", is_final=False)
                redir_ex.user_continuation = (
                    f"User interrupted you, and gave the following guidance: {redirect_msg}"
                )
                had_tool_calls = True
                current_subturn.exchanges.append(redir_ex)
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
                    exchange = await asyncio.to_thread(
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
                if not had_todo_items and session.session_data.get("todo_list"):
                    had_todo_items = True
                current_subturn.exchanges.append(exchange)
                # Save in-progress turn state to Redis after each tool batch
                _save_session(session_id, session)

                # Check cancel first — cancel takes priority over redirect.
                if cancel_event.is_set():
                    was_cancelled = True
                    break

                # Check redirect: _execute_tools returned early; inject guidance and continue.
                if redirect_event is not None and redirect_event.is_set():
                    # If soft_interrupt fired before the message arrived, wait for it now.
                    _msg_ready = _redirect_message_ready.pop(session_id, None)
                    if _msg_ready is not None and not _redirect_messages.get(session_id):
                        while not _msg_ready.is_set():
                            await asyncio.sleep(0.1)
                    redirect_msg = _redirect_messages.pop(session_id, "User interrupted.")
                    redirect_event.clear()
                    exchange.user_continuation = (
                        f"User interrupted you, and gave the following guidance: {redirect_msg}"
                    )
                    _save_session(session_id, session)
                    continue

                continue

            # No tool calls — this is a non-tool assistant response.
            # Check redirect first: it may have fired right as streaming ended
            # (within the watcher's 0.3s poll window), causing the watcher to
            # be cancelled before it could interrupt the LLM call.
            if redirect_event is not None and redirect_event.is_set():
                redirect_msg = _redirect_messages.pop(session_id, "User interrupted.")
                redirect_event.clear()
                redir_ex = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=False,
                )
                redir_ex.user_continuation = (
                    f"User interrupted you, and gave the following guidance: {redirect_msg}"
                )
                had_tool_calls = True
                current_subturn.exchanges.append(redir_ex)
                _save_session(session_id, session)
                continue

            # Run watchdog on every non-blank response, regardless of todo state or
            # prior history. This catches final answers written before todos are closed.
            is_candidate = False
            irat_flush_pending: tuple[str, int, str] | None = None  # (subturn_id, exchange_idx, text)
            if content_for_history and content_for_history.strip():
                is_candidate = await _is_sufficient_final_answer(
                    streaming_llm,
                    session,
                    current_turn,
                    current_subturn,
                    content_for_history,
                    watchdog_max_tokens,
                )
                if is_candidate:
                    pending_final_candidate = (content_for_history, reasoning)
                elif session.interim_response_as_thinking and is_interim_call:
                    # Watchdog says NO — schedule IRAT flush for this exchange.
                    # Emitted only if this exchange will be stored as an interim step.
                    irat_flush_pending = (current_subturn.id, exchange_idx, content_for_history)

            # Hard block: todos must be closed before the turn can end.
            unclosed = _get_open_items(session.session_data.get("todo_list") or [])
            if unclosed:
                if irat_flush_pending is not None:
                    _emit_and_log(session_id, "irat_thinking_flush", {
                        "turn_id": turn_id,
                        "subturn_id": irat_flush_pending[0],
                        "exchange_idx": irat_flush_pending[1],
                        "text": irat_flush_pending[2],
                    })
                items_text = "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(unclosed))
                continuation = f"You still have {len(unclosed)} unclosed todo item(s). Please continue:\n{items_text}"
                interim_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=False,
                    user_continuation=continuation,
                )
                current_subturn.exchanges.append(interim_exchange)
                _save_session(session_id, session)
                continue

            # All todos are closed. Choose the best final answer.

            if is_candidate:
                # Current response was rated sufficient — use it directly.
                # IRAT thinking is suppressed (this IS the answer, not thinking).
                final_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=True,
                )
                current_subturn.exchanges.append(final_exchange)
                _emit_and_log(session_id, "message_done", {
                    "content": content_for_history, "turn_id": turn_id,
                })
                if current_subturn.count_tool_calls() > 0:
                    await _generate_and_store_compaction(
                        streaming_llm, session_id, turn_id, current_subturn, content_for_history
                    )
                turn_completed = True
                break

            if pending_final_candidate is not None:
                # A prior response (possibly written before todos were closed) was
                # rated sufficient. Use it; discard the current weak closing remark.
                # IRAT thinking for the current exchange is suppressed (it's noise).
                cand_content, cand_reasoning = pending_final_candidate
                final_exchange = LLMExchange(
                    assistant_content=cand_content,
                    reasoning=cand_reasoning,
                    is_final=True,
                )
                current_subturn.exchanges.append(final_exchange)
                _emit_and_log(session_id, "message_done", {
                    "content": cand_content, "turn_id": turn_id,
                })
                if current_subturn.count_tool_calls() > 0:
                    await _generate_and_store_compaction(
                        streaming_llm, session_id, turn_id, current_subturn, cand_content
                    )
                turn_completed = True
                break

            if had_tool_calls and not final_summary_reprompt_sent:
                # No candidate found yet — ask model for an explicit final summary.
                if irat_flush_pending is not None:
                    _emit_and_log(session_id, "irat_thinking_flush", {
                        "turn_id": turn_id,
                        "subturn_id": irat_flush_pending[0],
                        "exchange_idx": irat_flush_pending[1],
                        "text": irat_flush_pending[2],
                    })
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
                current_subturn.exchanges.append(interim_exchange)
                _emit_and_log(session_id, "final_reprompt", {"turn_id": turn_id})
                _emit_and_log(session_id, "begin_final_summary", {"turn_id": turn_id})
                _save_session(session_id, session)
                continue

            # Final response: no tool calls, or response after explicit reprompt.
            # is_interim_call is False here so no IRAT to flush.
            final_exchange = LLMExchange(
                assistant_content=content_for_history,
                reasoning=reasoning,
                is_final=True,
            )
            current_subturn.exchanges.append(final_exchange)
            _emit_and_log(session_id, "message_done", {
                "content": content_for_history, "turn_id": turn_id,
            })
            if current_subturn.count_tool_calls() > 0:
                await _generate_and_store_compaction(
                    streaming_llm, session_id, turn_id, current_subturn, content_for_history
                )
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
            current_turn.finalize(session.session_data, last_assistant_content, had_todo_items)
            session.completed_turns.append(current_turn)
            session.current_turn = None
            _emit_and_log(session_id, "turn_cancelled", {"turn_id": turn_id})
            _emit_and_log(session_id, "message_done", {"content": None, "turn_id": turn_id})
        elif turn_completed:
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(session.session_data.get("todo_list") or [])
            current_turn.finalize(session.session_data, last_assistant_content, had_todo_items)
            session.completed_turns.append(current_turn)
            session.current_turn = None
        else:
            # Abnormal exit (unhandled error): ensure the frontend is unblocked.
            logger.error("Agent loop exited abnormally for session %s turn %s", session_id, turn_id)
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(session.session_data.get("todo_list") or [])
            current_turn.finalize(session.session_data, last_assistant_content, had_todo_items)
            session.completed_turns.append(current_turn)
            session.current_turn = None
            _emit_and_log(session_id, "message_done", {"content": last_assistant_content or None, "turn_id": turn_id})

        _save_session(session_id, session)
        return had_todo_items


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
        custom_skills = [
            entry for entry in _get_session_skill_registry(session_id)
            if entry["source"] == "custom"
        ]
        skills_str = f"enabled ({len(custom_skills)} skills)"
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


@socketio.on("soft_interrupt")
def handle_soft_interrupt():
    """Phase 1 of stop-and-redirect: fired immediately when the user opens the widget.
    Sets redirect_event right away so the LLM is interrupted while the user types.
    The loop will wait for the message (phase 2) before injecting guidance."""
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    # Create the message-ready gate BEFORE setting redirect_event to avoid a race
    # where the loop checks for the gate right after waking up.
    _redirect_message_ready[session_id] = threading.Event()
    ev = _redirect_events.get(session_id)
    if ev is not None:
        ev.set()
    # Wake pending blocking waits so they exit and check redirect_event promptly.
    pending_approval = _pending_approvals.get(sid)
    if pending_approval:
        pending_approval["event"].set()
    logger.info("Soft interrupt for session %s", session_id)


@socketio.on("stop_and_redirect")
def handle_stop_and_redirect(data):
    """Phase 2 of stop-and-redirect: delivers the user's redirect message.
    If soft_interrupt (phase 1) already fired, just signals the message-ready gate.
    Otherwise (e.g. stop-and-try-again which skips phase 1) behaves as before."""
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    message = (data or {}).get("message", "User interrupted turn, please try again.")
    _redirect_messages[session_id] = message
    ready_ev = _redirect_message_ready.get(session_id)
    if ready_ev is not None:
        # soft_interrupt already set redirect_event; just unblock the waiting loop.
        ready_ev.set()
    else:
        # Direct stop_and_redirect with no prior soft_interrupt (e.g. stop-and-try-again).
        ev = _redirect_events.get(session_id)
        if ev is not None:
            ev.set()
        # Wake pending blocking waits.
        pending_approval = _pending_approvals.get(sid)
        if pending_approval:
            pending_approval["event"].set()
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
        custom_skills = [
            entry for entry in _get_session_skill_registry(session_id)
            if entry["source"] == "custom"
        ]
        skill_labels = sorted(
            f"{entry['name']} ({entry['id']})" + (" [autoload]" if entry["autoload"] else "")
            for entry in custom_skills
        )
        socketio.emit("skills_info", {
            "enabled": True, "count": len(skill_labels),
            "path": skills_path.replace("\\", "/"), "files": skill_labels,
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

    # Determine continuation vs new turn before touching session state.
    _is_cont = False
    if session.completed_turns:
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
        # Re-open the last completed turn and append a new continuation subturn.
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

    _emit_and_log(session_id, "turn_start", {
        "turn_id": turn_id,
        "user_text": text,
        "subturn_id": subturn_id,
    })

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
            _had_todos = await _async_agent_loop(
                sid, session_id, session, streaming_llm,
                turn_id, current_turn, current_subturn,
                return_value_max_chars,
                cancel_event,
                watchdog_max_tokens=watchdog_max_tokens,
                redirect_event=redirect_event,
            )
            # Generate a title only if a todo list was ever created this turn.
            if _had_todos:
                await _fetch_and_store_title()
        except asyncio.CancelledError:
            # cancel_event already set inside _async_agent_loop's finally
            cancel_event.set()
        except Exception as exc:
            logger.exception("Unhandled exception in agent loop for session %s: %s", session_id, exc)
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


@socketio.on("force_continuation")
def handle_force_continuation(data: dict):
    """Force a continuation subturn, bypassing the continuation watchdog.
    Used by the Follow-Up button in the UI."""
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    if session_id in _cancel_tasks:
        emit("error", {"message": "A turn is already in progress. Please wait or cancel first."})
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    if not _sid_to_session_id.get(sid):
        return

    llm_config = _load_llm_config()
    if llm_config is None:
        emit("error", {"message": "No active token/endpoint configured. Run `slbp token use` first."})
        return

    session = _load_session(session_id)

    if not session.completed_turns:
        emit("error", {"message": "No previous turn to continue."})
        return

    streaming_llm = StreamingLLM(
        llm_config["endpoint_url"],
        llm_config["token_value"],
        60,
        llm_config["model"],
        llm_config["model_params"],
    )
    return_value_max_chars: int | None = llm_config["system_params"].get("return_value_max_chars")
    watchdog_max_tokens: int | None = llm_config["system_params"].get("watchdog_max_tokens")

    _effective_cwd = _session_current_cwd.get(session_id) or session.initial_cwd
    if _effective_cwd:
        try:
            os.chdir(_effective_cwd)
        except OSError as _chdir_err:
            _emit_backend_log(session_id, f"Warning: could not chdir to {_effective_cwd!r}: {_chdir_err}")

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

    _emit_and_log(session_id, "turn_start", {
        "turn_id": turn_id,
        "user_text": text,
        "subturn_id": subturn_id,
    })

    cancel_event = threading.Event()
    redirect_event = threading.Event()
    _redirect_events[session_id] = redirect_event

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _cancel_loops[session_id] = loop

    async def _run() -> None:
        task = asyncio.current_task()
        _cancel_tasks[session_id] = task
        try:
            await _async_agent_loop(
                sid, session_id, session, streaming_llm,
                turn_id, current_turn, current_subturn,
                return_value_max_chars,
                cancel_event,
                watchdog_max_tokens=watchdog_max_tokens,
                redirect_event=redirect_event,
            )
        except asyncio.CancelledError:
            cancel_event.set()
        except Exception as exc:
            logger.exception("Unhandled exception in force_continuation loop for session %s: %s", session_id, exc)
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

