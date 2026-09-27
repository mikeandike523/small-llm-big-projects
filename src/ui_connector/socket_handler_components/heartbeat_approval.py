"""Heartbeat approval policy: an extra layer over the normal approval decision.

It runs only after the agent loop has already decided a tool call needs
approval (the tool's own ``needs_approval`` plus the ``request_unredacted``
hard gate), and before any approval event reaches the UI -- so a forced
decision never opens a dialog. It applies only to subturns a heartbeat
started; a human's follow-up in the same turn waits for the human as usual.
"""

from __future__ import annotations

import logging

from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.emit import _emit_backend_log
from src.utils.heartbeat_settings import (
    HEARTBEAT_APPROVAL_POLICY_FORCE_APPROVE,
    HEARTBEAT_APPROVAL_POLICY_FORCE_FAIL,
)
from src.utils.session_model import SUBTURN_ORIGIN_HEARTBEAT, Session, Turn

logger = logging.getLogger(__name__)


def _subturn_origin(turn: Turn, subturn_id: str) -> str | None:
    for subturn in turn.subturns:
        if subturn.id == subturn_id:
            return subturn.origin
    return None


def heartbeat_approval_override(
    session_id: str,
    session: Session,
    turn: Turn,
    subturn_id: str,
    tool_name: str,
) -> bool | None:
    """Return the forced decision (True/False), or None to ask the human."""
    if _subturn_origin(turn, subturn_id) != SUBTURN_ORIGIN_HEARTBEAT:
        return None
    # Read live so a policy change takes effect at the next approval.
    policy = runtime_settings.snapshot(session_id, session).heartbeat_settings.get(
        "heartbeat_approval_policy"
    )
    if policy == HEARTBEAT_APPROVAL_POLICY_FORCE_FAIL:
        decision, verb = False, "denied"
    elif policy == HEARTBEAT_APPROVAL_POLICY_FORCE_APPROVE:
        decision, verb = True, "approved"
    else:
        return None
    message = (
        f"Heartbeat approval policy {policy}: auto-{verb} {tool_name} "
        f"(session_id={session_id} turn_id={turn.id})"
    )
    logger.info(message)
    _emit_backend_log(session_id, message)
    return decision
