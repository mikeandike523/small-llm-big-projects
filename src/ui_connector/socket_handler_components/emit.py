from __future__ import annotations

import logging
from typing import Callable

from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.utils.event_log import log_event, REPLAY_EXCLUDED_EVENTS

logger = logging.getLogger(__name__)


def _make_sampler_usage_tracker(session_id: str, label: str) -> Callable[[dict], None]:
    """Return a callback that logs sampler usage to the backend log and updates session cost."""
    def _track(usage: dict) -> None:
        if not usage:
            return
        cost = usage.get("cost")
        cost_str = ""
        if cost is not None:
            try:
                cost = float(cost)
                _state._session_costs[session_id] = (
                    _state._session_costs.get(session_id, 0.0) + cost
                )
                total_cost = _state._session_costs[session_id]
                socketio.emit(
                    "session_cost_update", {"total_usd": total_cost}, room=session_id
                )
                cost_str = f", cost=${cost:.6f} (session=${total_cost:.6f})"
            except (TypeError, ValueError):
                pass
        _emit_backend_log(
            session_id,
            colored(f"[sampler:{label}] ", "magenta")
            + f"prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')}, "
            f"total={usage.get('total_tokens', '?')}"
            + cost_str,
        )
    return _track


def _emit_backend_log(session_id: str, text: str) -> None:
    with _state._log_counter_lock:
        _state._log_counter += 1
        n = _state._log_counter
    socketio.emit("backend_log", {"id": n, "text": text}, room=session_id)


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
