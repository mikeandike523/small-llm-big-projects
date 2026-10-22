from __future__ import annotations

import logging
import uuid

from flask import jsonify
from termcolor import colored

from src.ui_connector.app import app
from src.logic.prompt_placeholders import PlaceholderContext, build_placeholder_values
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
)
from src.utils.session_dirs import ensure_session_dirs, get_session_workspace_dir
from src.utils.session_model import Session

logger = logging.getLogger(__name__)


def _build_prompt_placeholders(session: Session, session_id: str) -> PlaceholderContext:
    """Placeholder values for this session's system prompt and skill files.
    Unknown placeholders are left as written and reported to the Logs panel."""

    def _on_unknown(name: str, source: str) -> None:
        message = f"Unknown placeholder {{{{ {name} }}}} in {source}; left as written."
        logger.warning("%s (session %s)", message, session_id)
        _emit_backend_log(session_id, colored(message, "yellow", force_color=True))

    return PlaceholderContext(
        values=build_placeholder_values(session_id, session.initial_cwd),
        on_unknown=_on_unknown,
    )


def _ensure_session_dirs_reported(session: Session, session_id: str) -> None:
    """Ensure the session's folders exist when it loads. A failure is not fatal
    for an existing conversation, but it is never silent."""
    try:
        ensure_session_dirs(session_id, session.initial_cwd)
    except OSError as exc:
        logger.error("Could not create session folders for %s: %s", session_id, exc)
        _emit_and_log(
            session_id,
            "error",
            {"message": f"Could not create session folders: {exc}"},
        )


@app.route("/api/sessions/new-id", methods=["GET"])
def api_new_session_id():
    """Issue an id for a session that is about to be created, plus the
    workspace folder the New Session dialog suggests for it. Nothing is
    stored: the id only becomes a session when POST /api/sessions uses it."""
    session_id = str(uuid.uuid4())
    return jsonify(
        {
            "session_id": session_id,
            "workspace_dir": get_session_workspace_dir(session_id),
        }
    )
