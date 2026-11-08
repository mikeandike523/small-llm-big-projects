"""send_email: start a new email thread from the session's email address.

Offered only to sessions that answer email (a pool session, or a single session
with its email channel on); ``filter_unavailable`` drops it from the per-subturn
tool list otherwise, like a skill tool. See ``channels/email/new_email.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

TOOL_NAME = "send_email"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Send a new email from your email address, in a new email thread. Use "
            "it only when asked to email someone. Do NOT use it to answer the email "
            "you are handling: your final answer is sent as that reply "
            "automatically. Replies to this email are answered only if the "
            "recipient is on your allowlist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "One recipient email address, e.g. person@example.com.",
                },
                "subject": {
                    "type": "string",
                    "description": "The subject line.",
                },
                "body": {
                    "type": "string",
                    "description": (
                        "The message, in Markdown. It is sent as plain text plus "
                        "formatted HTML."
                    ),
                },
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
    },
}


def _agent_id_for(session_id: str) -> str | None:
    from src.utils.sql.agents_db import agent_id_for_session

    return agent_id_for_session(session_id)


def filter_unavailable(
    defs: list[dict], tool_map: dict, session_id: str, agent_id: str | None
) -> tuple[list[dict], dict]:
    """Drop send_email when this session cannot send email right now."""
    if TOOL_NAME not in tool_map:
        return defs, tool_map
    from src.channels.email.new_email import session_send_identity

    if session_send_identity(session_id, agent_id) is not None:
        return defs, tool_map
    kept = [d for d in defs if d.get("function", {}).get("name") != TOOL_NAME]
    return kept, {name: m for name, m in tool_map.items() if name != TOOL_NAME}


def needs_approval(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> bool:
    """As privileged as a write, but not an edit: only full-auto skips asking."""
    from src.tools._approval import is_full_auto

    return not is_full_auto(special_resources)


def _read_noreply_param() -> bool:
    from src.channels.email.email_runner import _read_global_param
    from src.channels.email.new_email import NOREPLY_NOTE_PARAM

    return bool(_read_global_param(NOREPLY_NOTE_PARAM))


def execute(
    args: dict, session_data: dict, special_resources: dict | None = None
) -> str:
    from src.channels.email.new_email import (
        build_send_client,
        clean_subject,
        send_new_email,
        session_send_identity,
    )
    from src.utils.email_addresses import InvalidEmailAddressError, parse_email_address

    session_id = str((special_resources or {}).get("session_id") or "")
    try:
        recipient = parse_email_address(str(args.get("to") or ""))
    except InvalidEmailAddressError as exc:
        return f"Error: invalid recipient address: {exc}"
    subject = clean_subject(str(args.get("subject") or ""))
    if not subject:
        return "Error: the subject is empty."
    body = str(args.get("body") or "")
    if not body.strip():
        return "Error: the body is empty."

    # Checked again here: email may have been turned off since the tool list
    # was built.
    identity = session_send_identity(session_id, _agent_id_for(session_id))
    if identity is None:
        return "Error: this session cannot send email (its email channel is off)."
    if recipient == identity.address:
        return "Error: you cannot email your own address."

    try:
        sent = send_new_email(
            build_send_client(),
            identity,
            recipient,
            subject,
            body,
            noreply_note_enabled=_read_noreply_param(),
        )
    except Exception as exc:
        logger.exception(
            "send_email failed: session_id=%s recipient=%s", session_id, recipient
        )
        return f"Error: the email could not be sent: {exc}"

    logger.info(
        "send_email sent: session_id=%s from=%s to=%s gmail_message_id=%s thread=%s",
        session_id,
        identity.address,
        recipient,
        sent.gmail_message_id,
        sent.gmail_thread_id,
    )
    if not sent.replies_answered:
        replies = (
            "Replies from this recipient will not be answered (not on the allowlist)."
        )
    elif identity.is_pool:
        replies = (
            "Replies from this recipient will be answered in a separate conversation."
        )
    else:
        replies = "Replies from this recipient will come back to this session."
    note = (
        " A note saying the address is not monitored was added."
        if sent.noreply_note_added
        else ""
    )
    return f'Email sent to {recipient} with subject "{subject}". {replies}{note}'
