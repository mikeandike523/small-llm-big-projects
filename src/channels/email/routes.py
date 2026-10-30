"""Portal-protected APIs used by the email debug page."""

from __future__ import annotations

from dataclasses import asdict

from flask import jsonify, request

from src.channels.email import get_email_config
from src.channels.email.debug_store import list_recent_threads
from src.channels.email.notification_store import pending_notification_count
from src.channels.email.state import load_mailbox_state
from src.ui_connector.app import app


@app.get("/api/email/status")
def email_status():
    config = get_email_config()
    if config is None:
        return jsonify(enabled=False, session_integration="not_implemented")
    state = asdict(load_mailbox_state(config.mailbox_email))
    return jsonify(
        enabled=True,
        mailbox_email=config.mailbox_email,
        alias_email=config.alias_email,
        pending_notifications=pending_notification_count(config.mailbox_email),
        session_integration="not_implemented",
        state=state,
    )


@app.get("/api/email/threads")
def email_threads():
    config = get_email_config()
    if config is None:
        return jsonify(error="email channel is disabled or unavailable"), 404
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    return jsonify(threads=list_recent_threads(limit))
