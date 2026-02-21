from __future__ import annotations

import json
import os
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
from src.tools import ALL_TOOL_DEFINITIONS, execute_tool, check_needs_approval
from src.logic.system_prompt import SYSTEM_PROMPT
from src.utils.request_error_formatting import format_http_error


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# Maps socket session ID to {"event": GreenEvent, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}


def _request_approval(sid: str, tool_id: str, tool_name: str, args: dict) -> bool:
    """
    Emit an approval_request event and block until the user approves or denies.
    Returns True if approved, False if denied.
    """
    import eventlet
    ev = eventlet.event.Event()
    _pending_approvals[sid] = {"event": ev, "approved": None}
    emit("approval_request", {"id": tool_id, "tool_name": tool_name, "args": args})
    ev.wait()  # yields green thread; unblocked by handle_approval_response
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
        return session
    return {
        "message_history": [{"role": "system", "content": SYSTEM_PROMPT}],
        "condensed_turns": [],
        "session_data": {},
    }


def _save_session(sid: str, session: dict) -> None:
    r = _get_redis()
    r.setex(f"session:{sid}", 3600, json.dumps(session))


def _delete_session(sid: str) -> None:
    r = _get_redis()
    r.delete(f"session:{sid}")


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
        llm_params = {k[len("params."):]: kv.get_value(k) for k in param_keys}

    if not token_value or not endpoint_url:
        return None

    return {"endpoint_url": endpoint_url, "token_value": token_value, "model": model, "params": llm_params}


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
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tools(result, content_for_history: str, session: dict, sid: str) -> tuple[bool, str | None]:
    """
    Append the assistant tool-call message, execute all tools, emit events,
    and append tool result messages to message_history.
    Returns (was_impossible, reason_or_none).
    """
    mh = session["message_history"]
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

        tool_result = execute_tool(tc.name, tc.arguments, session["session_data"])
        emit("tool_result", {"id": tc.id, "result": tool_result})
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


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    print(f"[ui_connector] Client disconnected: {sid}")
    _pending_approvals.pop(sid, None)
    _delete_session(sid)


@socketio.on("approval_response")
def handle_approval_response(data: dict):
    sid = request.sid
    tool_id = data.get("id")
    approved = bool(data.get("approved"))
    pending = _pending_approvals.get(sid)
    if pending:
        pending["approved"] = approved
        emit("approval_resolved", {"id": tool_id, "approved": approved})
        pending["event"].send()


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
        llm_config["params"],
    )

    session = _load_session(sid)
    session["message_history"].append({"role": "user", "content": text})
    turn_start_idx = len(session["message_history"]) - 1

    had_tool_calls = False
    final_reprompt_done = False
    was_impossible = False
    impossible_reason: str | None = None
    last_assistant_content = ""
    turn_completed = False

    while True:
        current_turn_slice = session["message_history"][turn_start_idx:]
        payload = _build_llm_payload(session["condensed_turns"], current_turn_slice)

        try:
            result, content_for_history = _run_llm_call(streaming_llm, payload)
        except requests.exceptions.HTTPError as exc:
            emit("error", {"message": f"LLM stream error:\n\n{format_http_error(exc)}"})
            break
        except Exception as exc:
            emit("error", {"message": f"LLM stream error:\n\n{exc}"})
            break

        last_assistant_content = content_for_history

        if result.has_tool_calls:
            impossible, reason = _execute_tools(result, content_for_history, session, sid)
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
            final_reprompt_done = True
            emit("final_reprompt", {})
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
