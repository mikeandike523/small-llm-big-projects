"""Automation approval policy: an extra layer over the normal approval decision.

It runs only after the agent loop has already decided a tool call needs
approval (the tool's own ``needs_approval`` under the session's approval
mode, plus the ``request_unredacted`` hard gate), and before any approval
event reaches the UI -- so a forced decision never opens a dialog.

It applies only to subturns an automation started: heartbeat subturns use
``heartbeat_settings.heartbeat_approval_policy`` and email subturns use
``email_settings.email_approval_policy``. A human's follow-up in the same
turn waits for the human as usual.
"""

from __future__ import annotations

import logging

from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.emit import _emit_backend_log
from src.utils.automation_approval_policies import (
    AUTOMATION_APPROVAL_POLICY_FORCE_APPROVE,
    AUTOMATION_APPROVAL_POLICY_FORCE_FAIL,
)
from src.utils.session_model import (
    SUBTURN_ORIGIN_EMAIL,
    SUBTURN_ORIGIN_HEARTBEAT,
    Session,
    Turn,
)

logger = logging.getLogger(__name__)

_ORIGIN_LABELS = {
    SUBTURN_ORIGIN_HEARTBEAT: "Heartbeat",
    SUBTURN_ORIGIN_EMAIL: "Email",
}


def _subturn_origin(turn: Turn, subturn_id: str) -> str | None:
    for subturn in turn.subturns:
        if subturn.id == subturn_id:
            return subturn.origin
    return None


def _policy_for(origin: str, session_id: str, session: Session) -> str | None:
    # Read live so a policy change takes effect at the next approval.
    settings = runtime_settings.snapshot(session_id, session)
    if origin == SUBTURN_ORIGIN_HEARTBEAT:
        return settings.heartbeat_settings.get("heartbeat_approval_policy")
    if origin == SUBTURN_ORIGIN_EMAIL:
        return settings.email_settings.get("email_approval_policy")
    return None


def automation_approval_override(
    session_id: str,
    session: Session,
    turn: Turn,
    subturn_id: str,
    tool_name: str,
) -> bool | None:
    """Return the forced decision (True/False), or None to ask the human."""
    origin = _subturn_origin(turn, subturn_id)
    if origin not in _ORIGIN_LABELS:
        return None
    policy = _policy_for(origin, session_id, session)
    if policy == AUTOMATION_APPROVAL_POLICY_FORCE_FAIL:
        decision, verb = False, "denied"
    elif policy == AUTOMATION_APPROVAL_POLICY_FORCE_APPROVE:
        decision, verb = True, "approved"
    else:
        return None
    message = (
        f"{_ORIGIN_LABELS[origin]} approval policy {policy}: auto-{verb} "
        f"{tool_name} (session_id={session_id} turn_id={turn.id})"
    )
    logger.info(message)
    _emit_backend_log(session_id, message)
    return decision
