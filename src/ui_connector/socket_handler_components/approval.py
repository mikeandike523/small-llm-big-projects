from __future__ import annotations

import threading

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import _emit_and_log


def _request_approval(
    sid: str,
    session_id: str,
    tool_id: str,
    tool_name: str,
    args: dict,
    turn_id: str = "",
    subturn_id: str = "",
    cancel_event: threading.Event | None = None,
) -> tuple[bool, str | None]:
    """
    Emit an approval_request event and block until approved, denied, or the
    turn is cancelled. Waits indefinitely — there is no timeout.
    Polls every 0.5s so cancel_event is checked promptly.
    Returns (approved, redirect_message). redirect_message is set when the user
    chose "Deny & Redirect" and typed a reason/suggestion.
    """
    ev = threading.Event()
    _state._pending_approvals[sid] = {
        "event": ev,
        "approved": None,
        "redirect_message": None,
        "turn_id": turn_id,
    }
    _emit_and_log(
        session_id,
        "approval_request",
        {
            "id": tool_id,
            "tool_name": tool_name,
            "args": args,
            "turn_id": turn_id,
            "subturn_id": subturn_id,
        },
    )

    while True:
        if ev.wait(timeout=0.5):
            break
        if cancel_event is not None and cancel_event.is_set():
            break

    entry = _state._pending_approvals.pop(sid, {})

    if cancel_event is not None and cancel_event.is_set():
        return False, None

    return bool(entry.get("approved", False)), entry.get("redirect_message")
