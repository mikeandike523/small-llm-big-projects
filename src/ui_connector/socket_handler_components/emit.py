from __future__ import annotations

import json
import logging
from typing import Callable

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.utils.event_log import log_event, REPLAY_EXCLUDED_EVENTS

logger = logging.getLogger(__name__)


def _make_sampler_callbacks(session_id: str, label: str) -> dict:
    """Return a dict of usage, request-log, and response callbacks for a sampler."""
    return {
        "on_usage": _make_sampler_usage_tracker(session_id, label),
        "on_request_log": _make_sampler_request_logger(session_id, label),
        "on_response": _make_sampler_response_logger(session_id, label),
    }


def _make_sampler_usage_tracker(session_id: str, label: str) -> Callable[[dict], None]:
    """Return a callback that logs sampler usage to the backend log and updates session cost."""
    def _track(usage: dict) -> None:
        if not usage:
            return
        cost = usage.get("cost")
        total_session_cost = _state._session_costs.get(session_id, 0.0)
        if cost is not None:
            try:
                cost = float(cost)
                _state._session_costs[session_id] = total_session_cost + cost
                total_session_cost = _state._session_costs[session_id]
                socketio.emit(
                    "session_cost_update",
                    {"total_usd": total_session_cost},
                    room=session_id,
                )
            except (TypeError, ValueError):
                cost = None
        _emit_backend_log(
            session_id,
            f"[sampler:{label}] usage",
            {
                "input_tokens": usage.get(
                    "input_tokens", usage.get("prompt_tokens", "?")
                ),
                "output_tokens": usage.get(
                    "output_tokens", usage.get("completion_tokens", "?")
                ),
                "total_tokens": usage.get("total_tokens", "?"),
                "cost": cost,
                "total_session_cost": total_session_cost,
            },
        )
    return _track


def _emit_backend_log(session_id: str, *contents) -> None:
    """Emit one backend log entry to the frontend.

    With one positional content argument, this preserves the legacy payload shape:
    ``{"id": n, "content": content}``.

    With two or more content arguments, the arguments are transported as one
    grouped/multi log entry: ``{"id": n, "multiple": True, "content": [...]}``.

    Content is sent to the frontend after a JSON round-trip that stringifies
    anything not natively JSON-safe (e.g. custom objects, sets) while leaving
    primitives/dicts/lists untouched.
    """
    if not contents:
        return

    with _state._log_counter_lock:
        _state._log_counter += 1
        n = _state._log_counter
    if len(contents) == 1:
        safe_content = json.loads(json.dumps(contents[0], default=str))
        payload = {"id": n, "content": safe_content}
    else:
        safe_content = json.loads(json.dumps(list(contents), default=str))
        payload = {"id": n, "multiple": True, "content": safe_content}
    socketio.emit("backend_log", payload, room=session_id)


def _emit_and_log(session_id: str, event_type: str, data: dict) -> None:
    """Emit a socket event to the session room and log it to Redis Streams (if not excluded)."""
    if event_type not in REPLAY_EXCLUDED_EVENTS:
        try:
            r = _state._get_redis()
            event_id = log_event(r, session_id, event_type, data)
            data = {**data, "event_id": event_id}
        except Exception as exc:
            logger.warning("Failed to log event %r: %s", event_type, exc)
    socketio.emit(event_type, data, room=session_id)


def _emit_content_snapshot(
    session_id: str,
    turn_id: str,
    subturn_id: str,
    exchange_idx: int,
    assistant_content: str,
    reasoning: str,
) -> None:
    """Emit a replay_content_snapshot event (logged to Redis Streams for replay)."""
    _emit_and_log(
        session_id,
        "replay_content_snapshot",
        {
            "turn_id": turn_id,
            "subturn_id": subturn_id,
            "exchange_idx": exchange_idx,
            "assistant_content": assistant_content,
            "reasoning": reasoning,
        },
    )


def _make_sampler_request_logger(session_id: str, sampler_name: str) -> Callable[[dict], None]:
    """Return a callback that logs the sampler request params to the backend log."""
    def _log(params: dict) -> None:
        _emit_backend_log(
            session_id,
            f"[sampler:{sampler_name}] request params",
            params if params else {"note": "(none)"},
        )
    return _log


def _make_sampler_response_logger(session_id: str, label: str):
    """Return a callback that logs system prompt, user message, reasoning, and assistant response."""
    def _log(messages, result) -> None:
        system_msg = ""
        user_msg = ""
        for m in messages:
            role = m.get("role", "")
            if role == "system" and not system_msg:
                system_msg = m.get("content", "") or ""
            elif role == "user" and not user_msg:
                user_msg = m.get("content", "") or ""
        _emit_backend_log(
            session_id,
            f"[sampler:{label}] response",
            {
                "system_prompt": system_msg,
                "user_message": user_msg,
                "assistant_response": result.content or "",
                "reasoning_text": result.reasoning or "",
                "reasoning_length": len(result.reasoning) if result.reasoning else 0,
            },
        )
    return _log
