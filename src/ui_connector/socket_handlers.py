from __future__ import annotations

import asyncio
import json
import os
import threading
import time
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
from src.logic.system_prompt import build_system_prompt
from src.utils.conversation_strip import strip_down_messages
from src.utils.emitting_kv_manager import EmittingKVManager
from src.utils.redis_dict import RedisDict
from src.utils.request_error_formatting import format_http_error
from src.utils.env_info import get_env_context, get_os, get_shell
from src.utils.session_model import (
    Session, Turn, LLMExchange, ToolCallRecord, CompactionRecord,
    session_to_dict, session_from_dict, turn_to_dict, turn_from_dict,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.event_log import log_event, get_events_since, REPLAY_EXCLUDED_EVENTS
from src.utils.exceptions import ToolHangError, ToolTimeoutError
from src.utils.docker_compose import get_service_port
from termcolor import colored

_BASE_SYSTEM_PROMPT: str = build_system_prompt(use_custom_skills=False)

_env_os = get_os()
_env_shell = get_shell()
_hotfix_bad_parser: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER") == "1"
_hotfix_void_call: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL") == "1"

# ---------------------------------------------------------------------------
# Per-session state caches (rebuilt from session data on load)
# ---------------------------------------------------------------------------

# session_id -> (tool_definitions, tool_map, plugin_info_list)
_session_tool_sets: dict[str, tuple[list, dict, list]] = {}
# session_id -> system_prompt_string
_session_system_prompts: dict[str, str] = {}
# session_id -> {initial_cwd, pin_project_memory} — lightweight cache for info handlers
_session_project_config: dict[str, dict] = {}
# session_id -> current working directory for this session (updated by change_pwd tool)
_session_current_cwd: dict[str, str] = {}


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
                print(f"[ui_connector] Custom tool loading failed for session {session_id}: {exc}", flush=True)
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
            use_custom_skills=bool(session.skills_path),
            custom_skills_path=session.skills_path,
        )

    _session_project_config[session_id] = {
        "initial_cwd": session.initial_cwd,
        "pin_project_memory": session.pin_project_memory,
    }

    # Track per-session CWD; only initialise if not already set so mid-session
    # navigation (change_pwd) survives across calls to _init_session_caches.
    if session_id not in _session_current_cwd:
        _session_current_cwd[session_id] = session.initial_cwd


# ---------------------------------------------------------------------------
# SID → session_id mapping (cleaned up on disconnect, NOT on session end)
# ---------------------------------------------------------------------------

_sid_to_session_id: dict[str, str] = {}

# Asyncio cancellation: maps session_id -> (event_loop, asyncio.Task)
# Replaces the old threading.Event _cancel_flags dict.
_cancel_loops: dict[str, asyncio.AbstractEventLoop] = {}
_cancel_tasks: dict[str, asyncio.Task] = {}


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
            print(f"[event_log] Failed to log event {event_type!r}: {exc}", flush=True)
    socketio.emit(event_type, data, room=session_id)


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# Maps socket session ID to {"event": threading.Event, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}

_APPROVAL_TIMEOUT = 60  # seconds


def _request_approval(
    sid: str,
    session_id: str,
    tool_id: str,
    tool_name: str,
    args: dict,
    turn_id: str = "",
    cancel_event: threading.Event | None = None,
) -> tuple[bool, str | None]:
    """
    Emit an approval_request event and block until approved, denied, timed out,
    or the turn is cancelled.
    Returns (approved, redirect_message). redirect_message is set when the user
    chose "Deny & Redirect" and typed a reason/suggestion.
    Polls every 0.5s so cancel_event is checked promptly.
    """
    ev = threading.Event()
    _pending_approvals[sid] = {"event": ev, "approved": None, "redirect_message": None, "turn_id": turn_id}
    _emit_and_log(session_id, "approval_request", {"id": tool_id, "tool_name": tool_name, "args": args, "turn_id": turn_id})

    deadline = time.monotonic() + _APPROVAL_TIMEOUT
    while time.monotonic() < deadline:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break

    entry = _pending_approvals.pop(sid, {})

    if cancel_event is not None and cancel_event.is_set():
        return False, None

    if not ev.is_set():
        _emit_and_log(session_id, "approval_timeout", {"id": tool_id, "tool_name": tool_name, "turn_id": turn_id})
        return False, None

    return bool(entry.get("approved", False)), entry.get("redirect_message")


# ---------------------------------------------------------------------------
# report_impossible redirect gate
# ---------------------------------------------------------------------------

# Maps socket session ID to pending redirect state
_pending_impossible_redirects: dict[str, dict] = {}

_IMPOSSIBLE_REDIRECT_TIMEOUT = 300  # 5 minutes — user needs time to read and type


def _request_impossible_redirect(
    sid: str,
    session_id: str,
    reason: str,
    turn_id: str,
    cancel_event: threading.Event | None,
) -> str | None:
    """
    Emit report_impossible_request and block until the user responds or times out.
    Returns redirect_message (str) if the user chose to redirect the LLM, or
    None if they chose "Truly Impossible" / timed out / cancelled.
    """
    ev = threading.Event()
    _pending_impossible_redirects[sid] = {
        "event": ev, "redirect_message": None, "turn_id": turn_id,
    }
    _emit_and_log(session_id, "report_impossible_request", {
        "reason": reason, "turn_id": turn_id,
    })

    deadline = time.monotonic() + _IMPOSSIBLE_REDIRECT_TIMEOUT
    while time.monotonic() < deadline:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break

    entry = _pending_impossible_redirects.pop(sid, {})

    if cancel_event is not None and cancel_event.is_set():
        return None

    return entry.get("redirect_message") or None


# ---------------------------------------------------------------------------
# ask_human gate
# ---------------------------------------------------------------------------

# Maps session_id to pending human input state (keyed by session_id, not sid,
# because the tool only has access to session_id via special_resources)
_pending_human_inputs: dict[str, dict] = {}

_ASK_HUMAN_TIMEOUT = 600  # 10 minutes


def _request_human_input(
    session_id: str,
    question: str,
    turn_id: str,
    cancel_event: threading.Event | None,
) -> str | None:
    """
    Emit ask_human_request and block until the user answers, cancels, or times out.
    Returns the user's answer string, or None on cancel / timeout.
    """
    ev = threading.Event()
    _pending_human_inputs[session_id] = {
        "event": ev, "answer": None, "turn_id": turn_id,
    }
    _emit_and_log(session_id, "ask_human_request", {
        "question": question, "turn_id": turn_id,
    })

    deadline = time.monotonic() + _ASK_HUMAN_TIMEOUT
    while time.monotonic() < deadline:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break

    entry = _pending_human_inputs.pop(session_id, {})

    if cancel_event is not None and cancel_event.is_set():
        return None

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
            print(f"[session_memory] _on_memory_change error (key={key!r}, session_id={session_id!r}): {exc}", flush=True)

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
    """Only called from CLI/test utilities, not from handle_disconnect."""
    r = _get_redis()
    r.delete(f"session:{session_id}")
    r.delete(f"session:{session_id}:memory")
    r.delete(f"session:{session_id}:events")
    _session_tool_sets.pop(session_id, None)
    _session_system_prompts.pop(session_id, None)
    _session_project_config.pop(session_id, None)
    _session_current_cwd.pop(session_id, None)


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
    )

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
        use_custom_skills=bool(skills_path),
        custom_skills_path=skills_path,
    )
    _session_project_config[session_id] = {
        "initial_cwd": initial_cwd,
        "pin_project_memory": pin_project_memory,
    }
    _session_current_cwd[session_id] = initial_cwd

    _save_session(session_id, session)

    print(f"[ui_connector] Session created: {session_id} cwd={initial_cwd!r}", flush=True)
    return jsonify({"session_id": session_id})


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
) -> tuple[object, str, str]:
    """
    Run one async LLM call (streaming) and emit token events.
    Returns (result, content_for_history, reasoning_accumulated).
    Raises on HTTP/network errors. Immediately cancellable via asyncio task cancellation.
    When interim_response_as_thinking=True, content tokens are emitted as type "reasoning"
    so the frontend displays them in the thinking panel instead of counting chars.
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
    )
    _emit_content_snapshot(session_id, turn_id, exchange_idx, acc["content"], acc["reasoning"])
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
) -> tuple[object, str, str]:
    """
    Run an async LLM call; on timeout or context-limit error, strip the payload
    and retry once.
    Returns (result, content_for_history, reasoning).
    """
    try:
        return await _async_run_llm_call(streaming_llm, payload, session_id, turn_id, exchange_idx, tool_defs, interim_response_as_thinking)
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
        return await _async_run_llm_call(streaming_llm, stripped, session_id, turn_id, exchange_idx, tool_defs, interim_response_as_thinking)


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
        "cancel_event": cancel_event,
        "ask_human_fn": lambda q: _request_human_input(session_id, q, turn_id, cancel_event),
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
            _emit_and_log(session_id, "tool_call", {
                "id": tc.id, "name": tc.name, "args": tc.arguments,
                "turn_id": turn_id,
            })

            tool_record = ToolCallRecord(id=tc.id, name=tc.name, args=tc.arguments)

            if check_needs_approval(tc.name, tc.arguments, tool_map=actual_tool_map):
                approved, redirect_message = _request_approval(
                    sid, session_id, tc.id, tc.name, tc.arguments,
                    turn_id=turn_id, cancel_event=cancel_event,
                )
                if not approved:
                    # If cancelled during approval, return without setting impossible flag —
                    # the caller checks cancel_event and handles the cancellation path.
                    if cancel_event is not None and cancel_event.is_set():
                        exchange.tool_calls.append(tool_record)
                        return False, None, exchange

                    denial = "DENIED: User did not approve this action."
                    tool_record.result = denial
                    exchange.tool_calls.append(tool_record)
                    _emit_and_log(session_id, "tool_result", {
                        "id": tc.id, "result": denial, "turn_id": turn_id,
                    })

                    if redirect_message:
                        # User chose "Deny & Redirect" — inject their guidance as a user
                        # continuation so the LLM pivots instead of ending the turn.
                        exchange.user_continuation = (
                            f"The user denied the tool call '{tc.name}' and provided this guidance: "
                            f"{redirect_message}\n\nPlease shift gears and follow the user's suggestion."
                        )
                        return False, None, exchange

                    reason = f"User denied approval to run '{tc.name}'."
                    session.session_data["_report_impossible"] = reason
                    was_impossible = True
                    return was_impossible, reason, exchange

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


async def _compact_exchanges(
    streaming_llm: StreamingLLM,
    exchanges: list[LLMExchange],
    max_tokens: int | None = None,
) -> str | None:
    """
    Make a non-streaming LLM call to summarise a sequence of exchanges.
    Returns the summary text, or None if the call fails or returns nothing useful.

    The payload is a minimal conversation:
      [user: ask to summarise]
      [assistant/tool messages from each exchange]
      [user: produce the summary]
    Internal control keys are stripped via sanitize_messages_for_llm before the
    payload is sent.
    """
    raw_messages: list[dict] = [
        {
            "role": "user",
            "content": (
                "Here are some problem-solving steps from an AI agent "
                "(tool calls and their results). Summarise them concisely "
                "in 2-4 sentences, highlighting the key actions and outcomes."
            ),
        }
    ]
    for exchange in exchanges:
        raw_messages.extend(exchange.to_messages())
    raw_messages.append({
        "role": "user",
        "content": "Provide your concise summary now.",
    })

    compaction_messages = sanitize_messages_for_llm(raw_messages)

    try:
        fetch_result = await asyncio.to_thread(
            streaming_llm.fetch, compaction_messages, max_tokens,
        )
        text = (fetch_result.content or "").strip()
        return text or None
    except Exception as exc:
        print(f"[compaction] LLM call failed: {exc}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Async agent loop
# ---------------------------------------------------------------------------

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
) -> None:
    """
    Main agentic loop. Runs inside a private asyncio event loop in the SocketIO thread.
    LLM calls are async (httpx) — immediately cancellable via asyncio task cancellation.
    Tool calls run in a thread pool (asyncio.to_thread) so the event loop stays responsive.
    """
    had_tool_calls = False
    final_reprompt_done = False
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

            is_interim_call = had_tool_calls and not final_reprompt_done
            if is_interim_call:
                _emit_and_log(session_id, "begin_interim_stream", {
                    "turn_id": turn_id,
                    "show_char_count": not session.interim_response_as_thinking,
                })

            exchange_idx = len(current_turn.exchanges)
            payload = _build_llm_payload(session, current_turn)

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
                )
            except asyncio.CancelledError:
                was_cancelled = True
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
                        session_tool_map,
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

                # Check cancel BEFORE processing impossible — cancel takes priority.
                if cancel_event.is_set():
                    was_cancelled = True
                    break

                # Early compaction: if any todo item was just closed, compact all
                # exchanges since the last compaction into a summary so the LLM
                # context does not grow unbounded during multi-step work.
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
                        _emit_and_log(session_id, "compaction_start", {
                            "turn_id": turn_id,
                            "exchange_indices": new_indices,
                            "item_label": item_label,
                        })
                        exchanges_to_compact = [current_turn.exchanges[i] for i in new_indices]
                        summary = await _compact_exchanges(
                            streaming_llm, exchanges_to_compact, max_tokens=compaction_max_tokens,
                        )
                        if summary:
                            cr = CompactionRecord(
                                summary_text=summary,
                                covers_exchange_indices=new_indices,
                            )
                            current_turn.compaction_records.append(cr)
                            _emit_and_log(session_id, "compaction_done", {
                                "turn_id": turn_id,
                                "summary_text": summary,
                                "item_label": item_label,
                            })
                            _emit_backend_log(
                                session_id,
                                colored(f"[compaction] Compacted {len(new_indices)} exchange(s) after closing: {item_label}", "magenta"),
                            )
                        else:
                            _emit_backend_log(
                                session_id,
                                colored("Compaction LLM call failed, continuing without summary.", "yellow"),
                            )
                        _save_session(session_id, session)

                if impossible:
                    redirect = _request_impossible_redirect(
                        sid, session_id, reason, turn_id, cancel_event,
                    )
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

            if had_tool_calls and not final_reprompt_done:
                todo_list = session.session_data.get("todo_list") or []
                all_closed = bool(todo_list) and not _get_open_items(todo_list)
                has_content = bool(content_for_history and content_for_history.strip())
                if all_closed and has_content:
                    # Interim wrap-up is the summary — no reprompt needed
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
                final_reprompt_done = True
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
        print(f"[ui_connector] Client connected without sessionId: {sid}", flush=True)
        return

    # Warn if another SID is already active for this session (multi-tab not supported).
    existing = [s for s, sess in _sid_to_session_id.items() if sess == session_id and s != sid]
    if existing:
        print(
            f"[ui_connector] WARNING: session {session_id} already has active SID(s) {existing}. "
            f"New SID {sid} also joining. Multi-tab is not supported.",
            flush=True,
        )

    print(f"[ui_connector] Client connected: {sid} -> session {session_id}", flush=True)
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
        print(f"[ui_connector] Event replay error for session {session_id}: {exc}", flush=True)
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
        print(f"[ui_connector] shell_output_snapshot error for session {session_id}: {exc}", flush=True)


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    session_id = _sid_to_session_id.pop(sid, None)
    print(f"[ui_connector] Client disconnected: {sid} (session={session_id})", flush=True)
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
    print(f"[ui_connector] Cancel requested for session {session_id}", flush=True)


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

    user_text_with_context = f"{text}\n\n{get_env_context(initial_cwd=session.initial_cwd or None)}"
    current_turn = Turn(
        id=turn_id,
        user_text=text,
        user_text_with_context=user_text_with_context,
    )
    session.current_turn = current_turn

    _emit_and_log(session_id, "turn_start", {"turn_id": turn_id, "user_text": text})

    # Create a threading.Event for subprocess tools and a private asyncio event loop
    # for real httpx-level LLM cancellation.
    cancel_event = threading.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _cancel_loops[session_id] = loop

    async def _run() -> None:
        task = asyncio.current_task()
        _cancel_tasks[session_id] = task
        try:
            await _async_agent_loop(
                sid, session_id, session, streaming_llm,
                turn_id, current_turn,
                return_value_max_chars, assistant_truncation_chars,
                cancel_event,
                compaction_max_tokens=compaction_max_tokens,
            )
        except asyncio.CancelledError:
            # cancel_event already set inside _async_agent_loop's finally
            cancel_event.set()
        finally:
            _cancel_tasks.pop(session_id, None)
            _cancel_loops.pop(session_id, None)

    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
