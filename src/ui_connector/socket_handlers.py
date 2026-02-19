from __future__ import annotations

import json
import os

import redis
from flask import request
from flask_socketio import emit
import requests

from src.ui_connector.app import socketio
from src.data import get_pool

_USE_STREAMING = os.environ.get("SLBP_STREAMING", "1") != "0"
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.tools import ALL_TOOL_DEFINITIONS, execute_tool
from src.logic.system_prompt import SYSTEM_PROMPT
from src.utils.request_error_formatting import format_http_error

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
        return json.loads(raw)
    return {
        "message_history": [{"role": "system", "content": SYSTEM_PROMPT}],
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
# Socket event handlers
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    print(f"[ui_connector] Client connected: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    print(f"[ui_connector] Client disconnected: {sid}")
    _delete_session(sid)


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

    # Agentic loop — streaming or non-streaming depending on SLBP_STREAMING env var
    had_tool_calls = False
    final_reprompt_done = False

    while True:
        if _USE_STREAMING:
            acc: dict[str, str] = {"reasoning": "", "content": ""}

            def on_data(chunk: dict) -> None:
                if chunk.get("reasoning"):
                    acc["reasoning"] += chunk["reasoning"]
                    emit("token", {"type": "reasoning", "text": chunk["reasoning"]})
                if chunk.get("content"):
                    acc["content"] += chunk["content"]
                    emit("token", {"type": "content", "text": chunk["content"]})

            try:
                result = streaming_llm.stream(
                    session["message_history"], on_data, tools=ALL_TOOL_DEFINITIONS
                )
            except requests.exceptions.HTTPError as exc:
                emit("error", {"message": f"LLM stream error:\n\n{format_http_error(exc)}"})
                break
            except Exception as exc:
                emit("error", {"message": f"LLM stream error:\n\n{exc}"})
                break
            content_for_history = acc["content"]
        else:
            try:
                result = streaming_llm.fetch(
                    session["message_history"], tools=ALL_TOOL_DEFINITIONS
                )
            except requests.exceptions.HTTPError as exc:
                emit("error", {"message": f"LLM error:\n\n{format_http_error(exc)}"})
                break
            except Exception as exc:
                emit("error", {"message": f"LLM error:\n\n{exc}"})
                break
            # Emit as single token events so the UI renders reasoning + content
            if result.reasoning:
                emit("token", {"type": "reasoning", "text": result.reasoning})
            if result.content:
                emit("token", {"type": "content", "text": result.content})
            content_for_history = result.content

        if result.has_tool_calls:
            session["message_history"].append({
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
                session["message_history"].append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

            had_tool_calls = True

            # Check if report_impossible was signalled
            if session["session_data"].get("_report_impossible"):
                reason = session["session_data"].pop("_report_impossible")
                emit("report_impossible", {"reason": reason})
                emit("message_done", {"content": None})
                break

            continue

        else:
            session["message_history"].append(
                {"role": "assistant", "content": content_for_history}
            )

            # Check for unclosed todo items — reprompt if any remain
            _todo_raw = session["session_data"].get("todo_list") or []
            _unclosed = [it for it in _todo_raw if it.get("status") != "closed"]
            if _unclosed:
                _items_text = "\n".join(
                    f"  {i + 1}. {it['text']}" for i, it in enumerate(_unclosed)
                )
                session["message_history"].append({
                    "role": "user",
                    "content": (
                        f"You still have {len(_unclosed)} unclosed todo item(s). "
                        f"Please continue:\n{_items_text}"
                    ),
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
            break

    _save_session(sid, session)
