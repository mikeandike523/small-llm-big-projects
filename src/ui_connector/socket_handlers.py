from __future__ import annotations

import json
import os
import threading
from typing import TypedDict

import redis
from flask import request
from flask_socketio import emit
import requests

from src.ui_connector.app import socketio
from src.data import get_pool

_USE_STREAMING = os.environ.get("SLBP_STREAMING", "1") != "0"
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.tools import ALL_TOOL_DEFINITIONS, execute_tool, check_needs_approval, _TOOL_MAP, _custom_tool_plugins
from src.logic.system_prompt import build_system_prompt
from src.utils.conversation_strip import strip_down_messages
from src.utils.emitting_kv_manager import EmittingKVManager
from src.utils.redis_dict import RedisDict
from src.utils.request_error_formatting import format_http_error
from src.utils.env_info import get_env_context, get_os, get_shell
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
# Backend log emitter
# ---------------------------------------------------------------------------

_log_counter = 0
_log_counter_lock = threading.Lock()


def _emit_backend_log(text: str) -> None:
    global _log_counter
    with _log_counter_lock:
        _log_counter += 1
        n = _log_counter
    emit("backend_log", {"id": n, "text": text})


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# Maps socket session ID to {"event": threading.Event, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}


def _request_approval(sid: str, tool_id: str, tool_name: str, args: dict) -> bool:
    """
    Emit an approval_request event and block until the user approves or denies.
    Returns True if approved, False if denied.
    """
    ev = threading.Event()
    _pending_approvals[sid] = {"event": ev, "approved": None}
    emit("approval_request", {"id": tool_id, "tool_name": tool_name, "args": args})
    ev.wait()  # blocks this OS thread; other threads handle concurrent socket events
    entry = _pending_approvals.pop(sid, {})
    return bool(entry.get("approved", False))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CondensedTurn(TypedDict):
    user: str
    assistant: str


# ---------------------------------------------------------------------------
# Redis session helpers
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


def _load_session(sid: str) -> dict:
    r = _get_redis()
    raw = r.get(f"session:{sid}")
    if raw:
        session = json.loads(raw)
        session.setdefault("condensed_turns", [])
    else:
        session = {
            "message_history": [{"role": "system", "content": SYSTEM_PROMPT}],
            "condensed_turns": [],
            "session_data": {},
        }

    mem_hash_key = f"session:{sid}:memory"

    def _on_memory_change(key: str, event_type: str) -> None:
        try:
            keys = r.hkeys(mem_hash_key)
            socketio.emit("session_memory_keys_update", {"keys": keys}, room=sid)
            socketio.emit("session_memory_key_event", {"key": key, "type": event_type}, room=sid)
        except Exception as exc:
            print(f"[session_memory] _on_memory_change error (key={key!r}, sid={sid!r}): {exc}", flush=True)

    # Memory lives in its own Redis hash, not the session blob.
    # Always attach a live RedisDict so tools see Redis-backed storage.
    # on_change fires on every write/delete, emitting live updates to the UI.
    session["session_data"]["memory"] = RedisDict(r, mem_hash_key, on_change=_on_memory_change)
    return session


def _save_session(sid: str, session: dict) -> None:
    r = _get_redis()
    # Exclude "memory" from the blob — it lives in session:{sid}:memory Redis hash.
    # Serialising a RedisDict via json.dumps would produce {} (empty internal dict).
    session_data_to_save = {k: v for k, v in session["session_data"].items() if k != "memory"}
    blob = {
        "message_history": session["message_history"],
        "condensed_turns": session["condensed_turns"],
        "session_data": session_data_to_save,
    }
    r.setex(f"session:{sid}", 3600, json.dumps(blob))
    # Keep the memory hash TTL in sync with the session blob TTL.
    r.expire(f"session:{sid}:memory", 3600)


def _delete_session(sid: str) -> None:
    r = _get_redis()
    r.delete(f"session:{sid}")
    r.delete(f"session:{sid}:memory")


# ---------------------------------------------------------------------------
# LLM config loader (reads from the DB the same way chat.py does)
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

def _build_llm_payload(
    condensed_turns: list[CondensedTurn],
    current_turn_slice: list[dict],
) -> list[dict]:
    """Assemble the message list actually sent to the LLM endpoint."""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in condensed_turns:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.extend(current_turn_slice)
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
    """Return True if exc is an HTTP error that indicates context-window overflow."""
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
    """Return True if exc is a network-level timeout."""
    return isinstance(exc, requests.exceptions.Timeout)


def _is_retryable_error(exc: Exception) -> bool:
    return _is_context_limit_error(exc) or _is_timeout_error(exc)


# ---------------------------------------------------------------------------
# LLM call abstraction
# ---------------------------------------------------------------------------

def _run_llm_call(streaming_llm: StreamingLLM, payload: list[dict]) -> tuple[object, str]:
    """
    Run one LLM call (streaming or non-streaming) and emit token events.
    Returns (result, content_for_history). Raises on HTTP/network errors.
    """
    if _USE_STREAMING:
        acc: dict[str, str] = {"content": ""}

        def on_data(chunk: dict) -> None:
            if chunk.get("reasoning"):
                emit("token", {"type": "reasoning", "text": chunk["reasoning"]})
            if chunk.get("content"):
                acc["content"] += chunk["content"]
                emit("token", {"type": "content", "text": chunk["content"]})

        result = streaming_llm.stream(payload, on_data, tools=ALL_TOOL_DEFINITIONS)
        return result, acc["content"]
    else:
        result = streaming_llm.fetch(payload, tools=ALL_TOOL_DEFINITIONS)
        if result.reasoning:
            emit("token", {"type": "reasoning", "text": result.reasoning})
        if result.content:
            emit("token", {"type": "content", "text": result.content})
        return result, result.content or ""


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _run_llm_call_with_retry(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    assistant_truncation_chars: int | None = None,
) -> tuple[object, str]:
    """
    Run an LLM call; on timeout or context-limit error, strip the payload
    down using each tool's LEAVE_OUT policy and retry once.
    Raises on any non-retryable error or if the retry also fails.
    """
    try:
        return _run_llm_call(streaming_llm, payload)
    except Exception as exc:
        if not _is_retryable_error(exc):
            raise

        reason = "timeout" if _is_timeout_error(exc) else "context limit exceeded"
        _emit_backend_log(
            colored(f"LLM call failed ({reason}), retrying with stripped context…", "yellow")
        )

        stripped = strip_down_messages(
            payload, _TOOL_MAP,
            assistant_truncation_chars=assistant_truncation_chars,
        )
        return _run_llm_call(streaming_llm, stripped)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _stub_tool_result(full_result: str, max_chars: int, session_data: dict) -> str:
    """
    Store full_result in session memory under a unique stubs.* key and return
    a truncated stub string the LLM can use to identify and retrieve it.
    """
    import secrets
    memory = session_data.setdefault("memory", {})
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


def _execute_tools(result, content_for_history: str, session: dict, sid: str, return_value_max_chars: int | None = None) -> tuple[bool, str | None]:
    """
    Append the assistant tool-call message, execute all tools, emit events,
    and append tool result messages to message_history.
    Returns (was_impossible, reason_or_none).
    """
    mh = session["message_history"]
    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, sid),
    }
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
    mh.append({
        "role": "assistant",
        "content": content_for_history or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in result.tool_calls
        ],
    })

    for tc in result.tool_calls:
        emit("tool_call", {"id": tc.id, "name": tc.name, "args": tc.arguments})

        if check_needs_approval(tc.name, tc.arguments):
            approved = _request_approval(sid, tc.id, tc.name, tc.arguments)
            if not approved:
                denial = f"DENIED: User did not approve this action."
                mh.append({"role": "tool", "tool_call_id": tc.id, "content": denial})
                emit("tool_result", {"id": tc.id, "result": denial})
                reason = f"User denied approval to run '{tc.name}'."
                session["session_data"]["_report_impossible"] = reason
                return True, reason

        session["session_data"]["__pinned_project__"] = _initial_cwd if _pin_project_memory else None
        tool_result = execute_tool(tc.name, tc.arguments, session["session_data"], special_resources)
        if return_value_max_chars is not None and len(tool_result) > return_value_max_chars:
            tool_result = _stub_tool_result(tool_result, return_value_max_chars, session["session_data"])
        emit("tool_result", {"id": tc.id, "result": tool_result})
        if tc.name == "change_pwd":
            emit("pwd_update", {"path": os.getcwd().replace("\\", "/")})
        if tc.name == "todo_list":
            _raw = session["session_data"].get("todo_list") or []
            emit("todo_list_update", {
                "items": [
                    {"item_number": i + 1, "text": it["text"], "status": it["status"]}
                    for i, it in enumerate(_raw)
                ]
            })
        mh.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": tool_result,
        })

    if session["session_data"].get("_report_impossible"):
        reason = session["session_data"].pop("_report_impossible")
        return True, reason
    return False, None


# ---------------------------------------------------------------------------
# Todo list helpers
# ---------------------------------------------------------------------------

def _get_closed_items(todo_list: list) -> list[str]:
    return [it["text"] for it in todo_list if it.get("status") == "closed"]


def _get_open_items(todo_list: list) -> list[str]:
    return [it["text"] for it in todo_list if it.get("status") != "closed"]


def _count_tool_messages(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("role") == "tool")


# ---------------------------------------------------------------------------
# Condensed turn builder
# ---------------------------------------------------------------------------

def _build_condensed_turn(
    user_text: str,
    had_tool_calls: bool,
    was_impossible: bool,
    n_tools: int,
    session_data: dict,
    final_content: str,
    impossible_reason: str | None,
) -> CondensedTurn:
    if not had_tool_calls:
        return {"user": user_text, "assistant": final_content}

    todo_list = session_data.get("todo_list") or []
    m = len(_get_closed_items(todo_list))
    open_items = _get_open_items(todo_list)

    if was_impossible:
        failed_text = ", ".join(open_items) if open_items else "none"
        thoughts = impossible_reason or final_content or ""
        assistant = (
            f"Hi, I could not complete your request. "
            f"I called {n_tools} tools, completed {m} todo items, "
            f"and could not complete: {failed_text}. "
            f"My final thoughts: {thoughts}"
        )
    else:
        assistant = (
            f"Hi. To complete your request, I called {n_tools} tools, "
            f"completed {m} todo items, and arrived at this answer/summary: "
            f"{final_content}"
        )

    return {"user": user_text, "assistant": assistant}


# ---------------------------------------------------------------------------
# Socket event handlers
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    print(f"[ui_connector] Client connected: {request.sid}")
    skills_str = f"enabled ({_skills_count} files)" if _skills_enabled else "disabled"
    _emit_backend_log(
        colored("System started", "green") +
        f": streaming={_USE_STREAMING}, skills={skills_str}, os={_env_os}, shell={_env_shell}"
    )


@socketio.on("run_startup_tool_calls")
def handle_run_startup_tool_calls():
    sid = request.sid
    if not _startup_tool_calls:
        emit("startup_tool_calls_done", {"count": 0})
        return

    session = _load_session(sid)
    special_resources = {
        "emitting_kv_manager": EmittingKVManager(get_pool(), socketio, sid),
    }

    for i, tc_spec in enumerate(_startup_tool_calls):
        name = tc_spec.get("name", "")
        args = tc_spec.get("args", {})
        tc_id = f"startup-{i}"

        emit("startup_tool_call", {"id": tc_id, "name": name, "args": args})

        session["session_data"]["__pinned_project__"] = _initial_cwd if _pin_project_memory else None
        try:
            result = execute_tool(name, args, session["session_data"], special_resources)
        except Exception as exc:
            result = f"Error executing '{name}': {exc}"

        emit("startup_tool_result", {"id": tc_id, "result": result})

        if name == "change_pwd":
            emit("pwd_update", {"path": os.getcwd().replace("\\", "/")})

    _save_session(sid, session)
    emit("startup_tool_calls_done", {"count": len(_startup_tool_calls)})


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    print(f"[ui_connector] Client disconnected: {sid}")
    _pending_approvals.pop(sid, None)
    _delete_session(sid)


@socketio.on("get_pwd")
def handle_get_pwd():
    emit("pwd_update", {"path": os.getcwd().replace("\\", "/")})


@socketio.on("get_skills_info")
def handle_get_skills_info():
    emit("skills_info", {"enabled": _skills_enabled, "count": _skills_count, "path": _skills_dir, "files": _skills_files})


@socketio.on("get_system_prompt")
def handle_get_system_prompt():
    emit("system_prompt", {"text": SYSTEM_PROMPT})


@socketio.on("get_env_info")
def handle_get_env_info():
    emit("env_info", {"os": _env_os, "shell": _env_shell, "initialCwd": _initial_cwd})


@socketio.on("get_session_memory_keys")
def handle_get_session_memory_keys():
    sid = request.sid
    keys = _get_redis().hkeys(f"session:{sid}:memory")
    emit("session_memory_keys_update", {"keys": keys})


@socketio.on("get_session_memory_value")
def handle_get_session_memory_value(data: dict):
    sid = request.sid
    key = data.get("key", "")
    # Read directly from the Redis hash — no session blob load needed.
    # Values are always plain strings (decode_responses=True on the Redis client).
    value = _get_redis().hget(f"session:{sid}:memory", key)
    if value is not None:
        emit("session_memory_value", {"key": key, "value": value, "found": True})
    else:
        emit("session_memory_value", {"key": key, "value": "", "found": False})


@socketio.on("get_project_memory_keys")
def handle_get_project_memory_keys():
    project = _get_default_project()
    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn).list_keys(project=project)
    emit("project_memory_keys_update", {"keys": keys})


@socketio.on("get_project_memory_value")
def handle_get_project_memory_value(data: dict):
    key = data.get("key", "")
    project = _get_default_project()
    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)
    if value is not None:
        # project_memory column is LONGTEXT and KVManager enforces strings on write,
        # so value should always be a str here. The non-string branch is a safety net
        # for any rows that existed before the JSON→LONGTEXT migration (v5.sql).
        value_str = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
        emit("project_memory_value", {"key": key, "value": value_str, "found": True})
    else:
        emit("project_memory_value", {"key": key, "value": "", "found": False})


@socketio.on("get_tools_info")
def handle_get_tools_info():
    custom_enabled = os.environ.get("SLBP_LOAD_CUSTOM_TOOLS") == "1"
    emit("tools_info", {
        "totalCount": len(ALL_TOOL_DEFINITIONS),
        "builtinCount": _builtin_tool_count,
        "builtinPath": "src/tools/",
        "names": [d["function"]["name"] for d in ALL_TOOL_DEFINITIONS],
        "customPlugins": _custom_tool_plugins if custom_enabled else None,
    })


@socketio.on("approval_response")
def handle_approval_response(data: dict):
    sid = request.sid
    tool_id = data.get("id")
    approved = bool(data.get("approved"))
    pending = _pending_approvals.get(sid)
    if pending:
        pending["approved"] = approved
        emit("approval_resolved", {"id": tool_id, "approved": approved})
        pending["event"].set()


@socketio.on("user_message")
def handle_user_message(data: dict):
    sid = request.sid
    text = (data.get("text") or "").strip()
    if not text:
        return

    llm_config = _load_llm_config()
    if llm_config is None:
        emit("error", {"message": "No active token/endpoint configured. Run `slbp token use` first."})
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

    session = _load_session(sid)
    session["session_data"]["todo_list"] = []
    emit("todo_list_update", {"items": []})
    user_content = f"{text}\n\n{get_env_context(initial_cwd=_initial_cwd)}"
    session["message_history"].append({"role": "user", "content": user_content})
    turn_start_idx = len(session["message_history"]) - 1

    had_tool_calls = False
    final_reprompt_done = False
    was_impossible = False
    impossible_reason: str | None = None
    last_assistant_content = ""
    turn_completed = False

    while True:
        # Emit a signal so the frontend knows this is an interim (pre-summary) stream
        if had_tool_calls and not final_reprompt_done:
            emit("begin_interim_stream", {})

        current_turn_slice = session["message_history"][turn_start_idx:]
        payload = _build_llm_payload(session["condensed_turns"], current_turn_slice)

        try:
            result, content_for_history = _run_llm_call_with_retry(
                streaming_llm, payload,
                assistant_truncation_chars=assistant_truncation_chars,
            )
        except requests.exceptions.HTTPError as exc:
            emit("error", {"message": f"LLM stream error:\n\n{format_http_error(exc)}"})
            break
        except Exception as exc:
            emit("error", {"message": f"LLM stream error:\n\n{exc}"})
            break

        usage = getattr(result, "usage", None)
        if usage:
            _emit_backend_log(
                colored("Usage: ", "cyan") +
                f"prompt={usage.get('prompt_tokens', '?')}, "
                f"completion={usage.get('completion_tokens', '?')}, "
                f"total={usage.get('total_tokens', '?')}"
            )

        last_assistant_content = content_for_history

        if result.has_tool_calls:
            impossible, reason = _execute_tools(result, content_for_history, session, sid, return_value_max_chars)
            had_tool_calls = True
            if impossible:
                was_impossible = True
                impossible_reason = reason
                emit("report_impossible", {"reason": reason})
                emit("message_done", {"content": None})
                turn_completed = True
                break
            continue

        # No tool calls — this is a non-tool assistant response
        session["message_history"].append({"role": "assistant", "content": content_for_history})

        unclosed = _get_open_items(session["session_data"].get("todo_list") or [])
        if unclosed:
            items_text = "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(unclosed))
            session["message_history"].append({
                "role": "user",
                "content": f"You still have {len(unclosed)} unclosed todo item(s). Please continue:\n{items_text}",
            })
            continue

        if had_tool_calls and not final_reprompt_done:
            todo_list = session["session_data"].get("todo_list") or []
            all_closed = bool(todo_list) and not _get_open_items(todo_list)
            has_content = bool(content_for_history and content_for_history.strip())
            if all_closed and has_content:
                # The interim wrap-up response is the summary — no reprompt needed.
                emit("message_done", {"content": content_for_history})
                turn_completed = True
                break
            final_reprompt_done = True
            emit("final_reprompt", {})
            emit("begin_final_summary", {})
            session["message_history"].append({
                "role": "user",
                "content": (
                    "All action items are complete. "
                    "Please provide your final summary or answer based on the steps "
                    "you took, the tool results, and the previous context."
                ),
            })
            continue

        emit("message_done", {"content": content_for_history})
        turn_completed = True
        break

    if turn_completed:
        n_tools = _count_tool_messages(session["message_history"][turn_start_idx:])
        condensed = _build_condensed_turn(
            user_text=text,
            had_tool_calls=had_tool_calls,
            was_impossible=was_impossible,
            n_tools=n_tools,
            session_data=session["session_data"],
            final_content=last_assistant_content,
            impossible_reason=impossible_reason,
        )
        session["condensed_turns"].append(condensed)

    _save_session(sid, session)
