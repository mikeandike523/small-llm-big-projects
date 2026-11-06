"""PATCH /api/sessions/<id>/email-settings (mirrors the heartbeat route).

One alias belongs to one session, and no agent may hold it. The pre-check gives
a friendly 409 naming the owner; the UNIQUE index on session_meta.email_alias
closes the race between two sessions (duplicate key -> the same 409), and
CLAIM_LOCK closes it between a session and an agent. A session in an agent's
pool has no email settings of its own, so it is refused.
"""

from __future__ import annotations

import logging
import time

from flask import jsonify, request

from src.ui_connector.app import app, socketio
from src.channels.email.inbound_store import discard_queued_for_session
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.http_api import (
    _agent_locked_response,
)
from src.ui_connector.socket_handler_components.session_store import (
    _load_session_info,
)
from src.ui_connector.socket_handler_components.setting_events import (
    persist_email_settings,
)
from src.utils.email_settings import (
    InvalidEmailSettingsError,
    parse_email_settings_input,
)
from src.utils.email_claims import CLAIM_LOCK, held_by_agent_message
from src.utils.sql.agents_db import is_duplicate_key_error
from src.utils.sql.email_alias_db import find_alias_owner

logger = logging.getLogger(__name__)


def _alias_conflict(alias: str, owner: dict | None):
    owner_title = (owner or {}).get("title")
    owner_label = f'"{owner_title}"' if owner_title else "another session"
    return (
        jsonify(
            {
                "error": (
                    f"{alias} is already used by {owner_label}. "
                    "Remove it from that session first."
                ),
                "field": "alias",
                "owner_session_id": (owner or {}).get("session_id"),
                "owner_title": owner_title,
            }
        ),
        409,
    )


@app.route("/api/sessions/<session_id>/email-settings", methods=["PATCH"])
def api_session_set_email_settings(session_id: str):
    """Change the email settings for a session (full replace)."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        incoming = parse_email_settings_input(data)
    except InvalidEmailSettingsError as exc:
        return jsonify({"error": str(exc), "field": exc.field}), 400

    session = _load_session_info(session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404
    if session.agent_id:
        return _agent_locked_response()

    current = runtime_settings.snapshot(session_id, session).email_settings
    alias = incoming["alias"]
    alias_changed = alias != (current.get("alias") or "")

    if not alias:
        claimed_at = None
    elif alias_changed or current.get("alias_claimed_at") is None:
        # Only mail Gmail receives after this moment is answered.
        claimed_at = time.time()
    else:
        claimed_at = current.get("alias_claimed_at")
    email_settings = {**incoming, "alias_claimed_at": claimed_at}

    with CLAIM_LOCK:
        if alias and alias_changed:
            owner = find_alias_owner(alias, exclude_session_id=session_id)
            if owner is not None:
                return _alias_conflict(alias, owner)
            held_by_agent = held_by_agent_message(alias)
            if held_by_agent is not None:
                return jsonify({"error": held_by_agent, "field": "alias"}), 409
        try:
            persist_email_settings(session_id, email_settings)
        except Exception as exc:
            if alias and is_duplicate_key_error(exc):
                return _alias_conflict(
                    alias, find_alias_owner(alias, exclude_session_id=session_id)
                )
            raise
    settings = runtime_settings.set_email_settings(session_id, session, email_settings)

    from src.channels.email.email_runner import notify_email_runner

    if alias_changed or not email_settings["enabled"]:
        discarded = discard_queued_for_session(session_id)
        if discarded:
            logger.info(
                "Email settings changed: discarded %d queued email(s) for "
                "session_id=%s (alias_changed=%s enabled=%s)",
                discarded,
                session_id,
                alias_changed,
                email_settings["enabled"],
            )
    notify_email_runner()

    response = {"ok": True, **runtime_settings.payload(settings)}
    socketio.emit("session_settings_update", response, room=session_id)
    return jsonify(response)
