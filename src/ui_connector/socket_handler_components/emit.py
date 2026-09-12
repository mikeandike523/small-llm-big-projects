from __future__ import annotations

import json
import logging
from typing import Callable

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.data import get_pool
from src.utils.event_log import log_event, REPLAY_EXCLUDED_EVENTS
from src.utils.param_registry import param_storage_key
from src.utils.sql.kv_manager import KVManager

logger = logging.getLogger(__name__)


def _make_sampler_callbacks(session_id: str, label: str) -> dict:
    """Return a dict of usage, request-log, and response callbacks for a sampler.

    Args:
        session_id: The session ID
        label: Label for this sampler (e.g., "tool", "skill_selector")

    Note: context_usage_event is intentionally NOT emitted from sampler
    callbacks — only the main agent exchange loop (agent_loop.py) emits
    context usage, so tool/auxiliary samplers never pollute that display.
    """
    return {
        "on_usage": _make_sampler_usage_tracker(session_id, label),
        "on_request_log": _make_sampler_request_logger(session_id, label),
        "on_response": _make_sampler_response_logger(session_id, label),
    }


def _make_sampler_usage_tracker(session_id: str, label: str) -> Callable[[dict], None]:
    """Return a callback that logs sampler usage to the backend log and updates session cost.

    Intentionally does NOT emit context_usage_event — that display is driven
    exclusively by the main agent exchange loop (agent_loop.py), so sampler
    usage from tools/auxiliary samplers never affects the context bar.

    Args:
        session_id: The session ID
        label: Label for this sampler (e.g., "tool", "skill_selector")
    """
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


def _emit_context_usage_if_configured(session_id: str, session_profile: str | None, usage: dict) -> None:
    """Emit context_usage_event to frontend if model.known_max_context parameter is set.

    This allows the frontend to display a visual indicator of context limit proximity.

    The emitted snapshot is also recorded in ``_state._session_last_context_usage``
    and flushed to ``session_meta`` on the next ``_save_session`` (same telemetry
    semantics as cost). Main-agent-only: sampler callbacks must NOT call this.
    """
    if not session_profile:
        return
    
    try:
        # Build the KV key for this profile's model.known_max_context parameter
        profile_prefix = f"profiles.{session_profile}."
        kv_key = param_storage_key("model.known_max_context", profile_prefix)
        
        # Try to get the parameter value from KV store
        try:
            pool = get_pool()
            with pool.get_connection() as conn:
                kv_manager = KVManager(conn)
                known_max_context = kv_manager.get_value(kv_key)
            
            # If the parameter is not set or is None, don't emit
            if known_max_context is None:
                return
            
            try:
                known_max_context = int(known_max_context)
            except (ValueError, TypeError):
                logger.warning(f"Invalid model.known_max_context value: {known_max_context}")
                return
            
            # If known_max_context is not positive, don't emit
            if known_max_context <= 0:
                return
            
            # Extract token counts from usage
            prompt_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
            completion_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            
            # Only emit if we have at least prompt and completion tokens
            if prompt_tokens is not None and completion_tokens is not None:
                snapshot = {
                    "prompt_tokens": int(prompt_tokens),
                    "completion_tokens": int(completion_tokens),
                    "total_tokens": int(total_tokens) if total_tokens is not None else None,
                    "known_max_context": known_max_context,
                }
                # Record for persistence (flushed to session_meta by _save_session).
                _state._session_last_context_usage[session_id] = snapshot
                socketio.emit("context_usage_event", snapshot, room=session_id)
        except Exception as e:
            logger.debug(f"Could not retrieve model.known_max_context parameter: {e}")
            return
    except Exception as e:
        logger.warning(f"Error in _emit_context_usage_if_configured: {e}")


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
