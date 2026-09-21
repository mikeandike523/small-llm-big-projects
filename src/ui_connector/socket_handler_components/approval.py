from __future__ import annotations

import threading

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import _emit_and_log


def _request_approval(
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
    Returns (approved, redirect_message, cancelled). redirect_message is set
    when the user chose "Deny & Redirect" and typed a reason/suggestion.
    cancelled is True only when the turn was cancelled with no explicit user
    decision recorded — the caller uses it to skip recording a denial.

    Keyed by session_id (not the Socket.IO connection sid): the durable session
    outlives any single connection, so a reconnect (e.g. after the client's
    machine sleeps) can still resolve an approval that was requested before it.
    """
    ev = threading.Event()
    _state._pending_approvals[session_id] = {
        "event": ev,
        "approved": None,
        "redirect_message": None,
        "turn_id": turn_id,
        "tool_id": tool_id,
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

    entry = _state._pending_approvals.pop(session_id, {})
    approved = entry.get("approved")

    if cancel_event is not None and cancel_event.is_set():
        if approved is False:
            # An explicit denial was recorded before the cancel arrived
            # (plain Deny, Deny & Stop, or Stop while the approval was
            # pending — see handle_cancel_turn, which resolves a pending
            # approval as denied). The denial survives so the caller records
            # the standard denial tool result.
            return False, entry.get("redirect_message"), False
        # Pure cancellation with no user decision (approved is None or True):
        # no denial is recorded. (An approval that raced with the cancel is
        # also dropped — the tool does not run on a cancelled turn.)
        return False, None, True

    return bool(approved), entry.get("redirect_message"), False
