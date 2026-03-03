from __future__ import annotations

import json
import os
import threading
from typing import Any

import redis
from flask import request
from flask_socketio import emit, join_room
import requests

from src.ui_connector.app import socketio
from src.data import get_pool

_USE_STREAMING = os.environ.get("SLBP_STREAMING", "1") != "0"
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.tools import ALL_TOOL_DEFINITIONS, execute_tool, check_needs_approval, _TOOL_MAP, _custom_tool_plugins
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui
from src.logic.system_prompt import build_system_prompt
from src.utils.conversation_strip import strip_down_messages
from src.utils.emitting_kv_manager import EmittingKVManager
from src.utils.redis_dict import RedisDict
from src.utils.request_error_formatting import format_http_error
from src.utils.env_info import get_env_context, get_os, get_shell
from src.utils.session_model import (
    Session, Turn, LLMExchange, ToolCallRecord,
    session_to_dict, session_from_dict, turn_to_dict, turn_from_dict,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.event_log import log_event, get_events_since, REPLAY_EXCLUDED_EVENTS
from termcolor import colored

SYSTEM_PROMPT = build_system_prompt(
    use_custom_skills=os.environ.get("SLBP_LOAD_SKILLS") == "1"
)

_env_os = get_os()
_env_shell = get_shell()
_initial_cwd: str = os.getcwd()
_pin_project_memory: bool = os.environ.get("SLBP_PIN_PROJECT_MEMORY", "1") != "0"
_hotfix_bad_parser: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER") == "1"
_hotfix_void_call: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL") == "1"


def _get_default_project() -> str:
    return _initial_cwd if _pin_project_memory else os.getcwd()


_skills_enabled = os.environ.get("SLBP_LOAD_SKILLS") == "1"
_skills_dir: str | None = None
_skills_files: list[str] = []
_skills_count: int = 0
if _skills_enabled:
    _skills_dir = os.path.join(os.getcwd(), "skills").replace("\\", "/")
    try:
        _skills_files = sorted(f for f in os.listdir(_skills_dir) if f.lower().endswith(".md"))
        _skills_count = len(_skills_files)
    except (FileNotFoundError, OSError):
        pass

_builtin_tool_count: int = len(ALL_TOOL_DEFINITIONS) - sum(p["count"] for p in _custom_tool_plugins)

_startup_tool_calls: list[dict] = []
if os.environ.get("SLBP_LOAD_STARTUP_TOOL_CALLS") == "1":
    _startup_path = os.path.join(_initial_cwd, "startup_tool_calls.json")
    try:
        with open(_startup_path, "r", encoding="utf-8") as _f:
            _startup_tool_calls = json.load(_f)
        print(f"[ui_connector] Loaded {len(_startup_tool_calls)} startup tool call(s) from {_startup_path}", flush=True)
    except FileNotFoundError:
        print(f"[ui_connector] startup_tool_calls.json not found at {_startup_path}", flush=True)
    except Exception as _exc:
        print(f"[ui_connector] Failed to load startup_tool_calls.json: {_exc}", flush=True)


# ---------------------------------------------------------------------------
# SID → session_id mapping (cleaned up on disconnect, NOT on session end)
# ---------------------------------------------------------------------------

_sid_to_session_id: dict[str, str] = {}

# Maps session_id -> Event; set by handle_cancel_turn to signal the running agentic loop
_cancel_flags: dict[str, threading.Event] = {}


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


def _request_approval(sid: str, session_id: str, tool_id: str, tool_name: str, args: dict) -> bool:
    """
    Emit an approval_request event and block until approved, denied, or timed out.
    Returns True if approved, False otherwise.
    """
    ev = threading.Event()
    _pending_approvals[sid] = {"event": ev, "approved": None}
    _emit_and_log(session_id, "approval_request", {"id": tool_id, "tool_name": tool_name, "args": args})
    timed_out = not ev.wait(timeout=_APPROVAL_TIMEOUT)
    entry = _pending_approvals.pop(sid, {})
    if timed_out:
        _emit_and_log(session_id, "approval_timeout", {"id": tool_id, "tool_name": tool_name})
        return False
    return bool(entry.get("approved", False))


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

_redis_client: redis.Redis | None = None

def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
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


# ---------------------------------------------------------------------------
# LLM config loader
# ---------------------------------------------------------------------------

def _load_llm_config() -> dict | None:
    """Return dict with endpoint_url, token_value, model or None on failure."""
    try:
        pool = get_pool()
    except Exception as exc:
        print(f"[ui_connector] DB pool error: {exc}")
        return None

    with pool.get_connection() as conn:
        kv = KVManager(conn)
        active_token = kv.get_value("active_token")
        if not active_token:
            return None

        provider = active_token["provider"]
        token_name = active_token.get("name", "")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_value, endpoint_url
                FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, token_name),
            )
            row = cursor.fetchone()

        if not row:
            return None

        token_value, endpoint_url = row

        model = kv.get_value("model") or None
        param_keys = kv.list_keys(prefix="params.")
        model_params = {
            k[len("params.model."):]: kv.get_value(k)
            for k in param_keys if k.startswith("params.model.")
        }
        system_params = {
            k[len("params.system."):]: kv.get_value(k)
            for k in param_keys if k.startswith("params.system.")
        }

    if not token_value or not endpoint_url:
        return None

    return {
        "endpoint_url": endpoint_url,
        "token_value": token_value,
        "model": model,
        "model_params": model_params,
        "system_params": system_params,
    }


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------

def _build_llm_payload(session: Session, current_turn: Turn) -> list[dict]:
    """Assemble the message list actually sent to the LLM endpoint."""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        if not isinstance(exc, requests.exceptions.HTTPError):
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
    return isinstance(exc, requests.exceptions.Timeout)


def _is_retryable_error(exc: Exception) -> bool:
    return _is_context_limit_error(exc) or _is_timeout_error(exc)


# ---------------------------------------------------------------------------
# LLM call abstraction
# ---------------------------------------------------------------------------

def _run_llm_call(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    exchange_idx: int,
    is_cancelled: Any = None,
) -> tuple[object, str, str]:
    """
    Run one LLM call (streaming or non-streaming) and emit token events.
    Returns (result, content_for_history, reasoning_accumulated).
    Raises on HTTP/network errors.
    """
    if _USE_STREAMING:
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
                socketio.emit("token", {
                    "type": "content", "text": chunk["content"],
                    "turn_id": turn_id,
                }, room=session_id)
                token_count += 1
                if token_count % 50 == 0:
                    _emit_content_snapshot(session_id, turn_id, exchange_idx, acc["content"], acc["reasoning"])

        result = streaming_llm.stream(payload, on_data, tools=ALL_TOOL_DEFINITIONS, is_cancelled=is_cancelled)
        # Emit final snapshot
        _emit_content_snapshot(session_id, turn_id, exchange_idx, acc["content"], acc["reasoning"])
        return result, acc["content"], acc["reasoning"]
    else:
        acc_r: dict[str, str] = {"reasoning": ""}
        result = streaming_llm.fetch(payload, tools=ALL_TOOL_DEFINITIONS)
        if result.reasoning:
            socketio.emit("token", {
                "type": "reasoning", "text": result.reasoning,
                "turn_id": turn_id,
            }, room=session_id)
            acc_r["reasoning"] = result.reasoning
        if result.content:
            socketio.emit("token", {
                "type": "content", "text": result.content,
                "turn_id": turn_id,
            }, room=session_id)
        content = result.content or ""
        _emit_content_snapshot(session_id, turn_id, exchange_idx, content, acc_r["reasoning"])
        return result, content, acc_r["reasoning"]


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
# Retry wrapper
# ---------------------------------------------------------------------------

def _run_llm_call_with_retry(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    exchange_idx: int,
    assistant_truncation_chars: int | None = None,
    is_cancelled: Any = None,
) -> tuple[object, str, str]:
    """
    Run an LLM call; on timeout or context-limit error, strip the payload
    and retry once.
    Returns (result, content_for_history, reasoning).
    """
    try:
        return _run_llm_call(streaming_llm, payload, session_id, turn_id, exchange_idx, is_cancelled=is_cancelled)
    except Exception as exc:
        if not _is_retryable_error(exc):
            raise

        reason = "timeout" if _is_timeout_error(exc) else "context limit exceeded"
        _emit_backend_log(
            session_id,
            colored(f"LLM call failed ({reason}), retrying with stripped context…", "yellow")
        )

        stripped = strip_down_messages(
            payload, _TOOL_MAP,
            assistant_truncation_chars=assistant_truncation_chars,
        )
        return _run_llm_call(streaming_llm, stripped, session_id, turn_id, exchange_idx, is_cancelled=is_cancelled)


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
) -> tuple[bool, str | None, LLMExchange]:
    """
    Execute all tool calls in result, emit events, and build an LLMExchange record.
    Returns (was_impossible, reason_or_none, exchange).
    Always pops _report_impossible from session_data before returning.
    """
    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, session_id),
    }
    turn_id = current_turn.id

    if _hotfix_bad_parser:
        for tc in result.tool_calls:
            if "<|channel|>" in tc.name:
                clean = tc.name.split("<|channel|>")[0]
                if clean in _TOOL_MAP:
                    tc.name = clean
    if _hotfix_void_call:
        for tc in result.tool_calls:
            module = _TOOL_MAP.get(tc.name)
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

            if check_needs_approval(tc.name, tc.arguments):
                approved = _request_approval(sid, session_id, tc.id, tc.name, tc.arguments)
                if not approved:
                    denial = "DENIED: User did not approve this action."
                    tool_record.result = denial
                    exchange.tool_calls.append(tool_record)
                    _emit_and_log(session_id, "tool_result", {
                        "id": tc.id, "result": denial, "turn_id": turn_id,
                    })
                    reason = f"User denied approval to run '{tc.name}'."
                    session.session_data["_report_impossible"] = reason
                    was_impossible = True
                    return was_impossible, reason, exchange

            session.session_data["__pinned_project__"] = _initial_cwd if _pin_project_memory else None
            tool_result = execute_tool(tc.name, tc.arguments, session.session_data, special_resources)
            if return_value_max_chars is not None and len(tool_result) > return_value_max_chars:
                tool_result = _stub_tool_result(tool_result, return_value_max_chars, session.session_data)
                tool_record.was_stubbed = True

            tool_record.result = tool_result
            exchange.tool_calls.append(tool_record)

            _emit_and_log(session_id, "tool_result", {
                "id": tc.id, "result": tool_result, "turn_id": turn_id,
            })
            if tc.name == "change_pwd":
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
# Socket event handlers
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    sid = request.sid
    session_id = request.args.get("sessionId", "")
    if not session_id:
        print(f"[ui_connector] Client connected without sessionId: {sid}", flush=True)
        return
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
    skills_str = f"enabled ({_skills_count} files)" if _skills_enabled else "disabled"
    _emit_backend_log(
        session_id,
        colored("System started", "green") +
        f": streaming={_USE_STREAMING}, skills={skills_str}, os={_env_os}, shell={_env_shell}"
    )

    if session.schema_version != CURRENT_SCHEMA_VERSION:
        emit("session_state", {"schemaInvalid": True})
        return

    completed_turns_data = [turn_to_dict(t) for t in session.completed_turns]
    current_turn_data = turn_to_dict(session.current_turn) if session.current_turn else None
    emit("session_state", {
        "startupDone": session.startup_done,
        "completedTurns": completed_turns_data,
        "currentTurn": current_turn_data,
    })

    # Always emit event_replay (even if empty) — frontend uses it as the "restore done" signal
    try:
        r = _get_redis()
        events = get_events_since(r, session_id, last_event_id)
    except Exception as exc:
        print(f"[ui_connector] Event replay error for session {session_id}: {exc}", flush=True)
        events = []
    emit("event_replay", {"events": events})


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
    flag = _cancel_flags.get(session_id)
    if flag:
        flag.set()
    print(f"[ui_connector] Cancel requested for session {session_id}", flush=True)


@socketio.on("get_pwd")
def handle_get_pwd():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    socketio.emit("pwd_update", {"path": os.getcwd().replace("\\", "/")}, room=session_id)


@socketio.on("get_skills_info")
def handle_get_skills_info():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    socketio.emit("skills_info", {
        "enabled": _skills_enabled, "count": _skills_count,
        "path": _skills_dir, "files": _skills_files,
    }, room=session_id)


@socketio.on("get_system_prompt")
def handle_get_system_prompt():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    socketio.emit("system_prompt", {"text": SYSTEM_PROMPT}, room=session_id)


@socketio.on("get_env_info")
def handle_get_env_info():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    socketio.emit("env_info", {
        "os": _env_os, "shell": _env_shell, "initialCwd": _initial_cwd,
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
    project = _get_default_project()
    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn).list_keys(project=project)
    socketio.emit("project_memory_keys_update", {"keys": keys}, room=session_id)


@socketio.on("get_project_memory_value")
def handle_get_project_memory_value(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid, sid)
    key = data.get("key", "")
    project = _get_default_project()
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
    custom_enabled = os.environ.get("SLBP_LOAD_CUSTOM_TOOLS") == "1"
    socketio.emit("tools_info", {
        "totalCount": len(ALL_TOOL_DEFINITIONS),
        "builtinCount": _builtin_tool_count,
        "builtinPath": "src/tools/",
        "names": [d["function"]["name"] for d in ALL_TOOL_DEFINITIONS],
        "customPlugins": _custom_tool_plugins if custom_enabled else None,
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
        _emit_and_log(session_id, "approval_resolved", {"id": tool_id, "approved": approved})
        pending["event"].set()


@socketio.on("run_startup_tool_calls")
def handle_run_startup_tool_calls():
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        emit("startup_tool_calls_done", {"count": 0})
        return

    if not _startup_tool_calls:
        socketio.emit("startup_tool_calls_done", {"count": 0}, room=session_id)
        return

    session = _load_session(session_id)
    if session.startup_done:
        socketio.emit("startup_tool_calls_done", {"count": 0, "skipped": True}, room=session_id)
        return

    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, session_id),
    }

    for i, tc_spec in enumerate(_startup_tool_calls):
        name = tc_spec.get("name", "")
        args = tc_spec.get("args", {})
        tc_id = f"startup-{i}"

        socketio.emit("startup_tool_call", {"id": tc_id, "name": name, "args": args}, room=session_id)

        session.session_data["__pinned_project__"] = _initial_cwd if _pin_project_memory else None
        try:
            result = execute_tool(name, args, session.session_data, special_resources)
        except Exception as exc:
            result = f"Error executing '{name}': {exc}"

        socketio.emit("startup_tool_result", {"id": tc_id, "result": result}, room=session_id)

        if name == "change_pwd":
            socketio.emit("pwd_update", {"path": os.getcwd().replace("\\", "/")}, room=session_id)

    session.startup_done = True
    _save_session(session_id, session)
    socketio.emit("startup_tool_calls_done", {"count": len(_startup_tool_calls)}, room=session_id)


@socketio.on("user_message")
def handle_user_message(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    turn_id: str = data.get("clientTurnId") or ""
    if not turn_id:
        import uuid
        turn_id = str(uuid.uuid4())

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

    session = _load_session(session_id)
    session.session_data["todo_list"] = []
    _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})

    user_text_with_context = f"{text}\n\n{get_env_context(initial_cwd=_initial_cwd)}"
    current_turn = Turn(
        id=turn_id,
        user_text=text,
        user_text_with_context=user_text_with_context,
    )
    session.current_turn = current_turn

    _emit_and_log(session_id, "turn_start", {"turn_id": turn_id, "user_text": text})

    cancel_event = threading.Event()
    _cancel_flags[session_id] = cancel_event

    had_tool_calls = False
    final_reprompt_done = False
    was_impossible = False
    impossible_reason: str | None = None
    was_cancelled = False
    last_assistant_content = ""
    turn_completed = False

    while True:
        if cancel_event.is_set():
            was_cancelled = True
            break

        if had_tool_calls and not final_reprompt_done:
            _emit_and_log(session_id, "begin_interim_stream", {"turn_id": turn_id})

        exchange_idx = len(current_turn.exchanges)
        payload = _build_llm_payload(session, current_turn)

        try:
            result, content_for_history, reasoning = _run_llm_call_with_retry(
                streaming_llm, payload,
                session_id=session_id,
                turn_id=turn_id,
                exchange_idx=exchange_idx,
                assistant_truncation_chars=assistant_truncation_chars,
                is_cancelled=cancel_event.is_set,
            )
        except requests.exceptions.HTTPError as exc:
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
            impossible, reason, exchange = _execute_tools(
                result, content_for_history, session, sid, session_id, current_turn,
                return_value_max_chars,
            )
            exchange.reasoning = reasoning
            had_tool_calls = True
            current_turn.exchanges.append(exchange)
            # Save in-progress turn state to Redis after each tool batch
            _save_session(session_id, session)

            if impossible:
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
            if cancel_event.is_set():
                was_cancelled = True
                break
            continue

        # No tool calls — this is a non-tool assistant response
        # Check for unclosed todos
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
            # Add the interim exchange with a continuation asking for final summary
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

    _cancel_flags.pop(session_id, None)
    _save_session(session_id, session)
