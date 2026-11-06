"""Inbound routing: decide which agents (if any) should handle an email.

Runs during history sync for messages relevant to a registered agent email. It
only writes queue rows; it never sends mail (sync holds a lease, and sending is
the runner's job) and never creates a session, so dropped mail spawns nothing.
Drop rules, in order:

1. our own / outbound mail;
2. auto-generated mail (``Auto-Submitted`` other than ``no``, bulk/list
   ``Precedence``) -- prevents auto-responder loops;
3. no recipient header names a registered agent -> silent (the mailbox is
   shared with unrelated automation);
4. per agent: disabled, or Gmail received the message before the agent's email
   was registered;
5. sender not on the agent's allowlist, or failing DMARC -> WARNING log
   "Possible malicious/unknown email".
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from email.utils import parseaddr

from src.channels.email.auth_results import evaluate_sender_authentication
from src.channels.email.filtering import recipient_addresses
from src.channels.email.inbound_store import (
    NewInboundEmail,
    conversation_has_unfinished_work,
    insert_inbound,
    sent_final_texts,
)
from src.channels.email.mime import ParsedGmailMessage
from src.channels.email.quote_strip import strip_trailing_quote
from src.utils.email_addresses import ascii_lower, header_sender_address
from src.utils.sql.agents_db import Agent, load_agents_for_emails

logger = logging.getLogger(__name__)

_AUTOMATED_PRECEDENCE = {"bulk", "junk", "list", "auto_reply"}
_DISPLAY_NAME_MAX_CHARS = 255


def is_automated_message(message: ParsedGmailMessage) -> bool:
    auto_submitted = ascii_lower(message.auto_submitted_header.strip())
    if auto_submitted and auto_submitted.split(";", 1)[0].strip() != "no":
        return True
    return ascii_lower(message.precedence_header.strip()) in _AUTOMATED_PRECEDENCE


def sender_display_name(from_header: str) -> str | None:
    """The name in a From header. The sender sets it freely, so it is only for
    showing on the dashboard and naming a folder, never for identifying anyone."""
    name, _address = parseaddr(from_header or "")
    name = " ".join(name.split())[:_DISPLAY_NAME_MAX_CHARS]
    return name or None


def _log_unknown(sender: str | None, raw_from: str, agent: Agent, reason: str):
    logger.warning(
        "Possible malicious/unknown email: sender=%s from_header=%r alias=%s "
        "agent_id=%s time=%s reason=%s",
        sender or "(unparseable)",
        raw_from,
        agent.email,
        agent.id,
        time.strftime("%Y-%m-%d %H:%M:%S %z"),
        reason,
    )


def route_inbound_message(
    message: ParsedGmailMessage,
    *,
    on_queued: Callable[[str], None] | None = None,
) -> list[str]:
    """Queue the message for every agent that should answer it.

    Returns the agent ids that newly queued it (redelivery queues nothing).
    """
    if message.direction == "outbound" or "SENT" in message.labels:
        return []
    if is_automated_message(message):
        logger.info(
            "Email ignored (automated message): gmail_message_id=%s",
            message.gmail_message_id,
        )
        return []
    agents = load_agents_for_emails(recipient_addresses(message))
    if not agents:
        return []

    sender = header_sender_address(message.from_header)
    received_at = message.internal_date_ms / 1000.0
    queued_for: list[str] = []
    for agent in agents:
        if not agent.enabled:
            logger.info(
                "Email ignored (agent disabled): alias=%s agent_id=%s "
                "gmail_message_id=%s",
                agent.email,
                agent.id,
                message.gmail_message_id,
            )
            continue
        if agent.registered_at is None or received_at < agent.registered_at:
            logger.info(
                "Email ignored (received before the agent's email was registered): "
                "alias=%s agent_id=%s gmail_message_id=%s",
                agent.email,
                agent.id,
                message.gmail_message_id,
            )
            continue
        if sender is None or sender not in set(agent.allowed_senders):
            _log_unknown(sender, message.from_header, agent, "sender not allowed")
            continue
        verdict = evaluate_sender_authentication(message.authentication_results, sender)
        if not verdict.passed:
            _log_unknown(sender, message.from_header, agent, verdict.reason)
            continue

        body = strip_trailing_quote(
            message.text_body,
            sent_final_texts(agent.id, message.gmail_thread_id, sender),
        )
        busy = conversation_has_unfinished_work(
            agent.id, message.gmail_thread_id, sender
        )
        inserted = insert_inbound(
            NewInboundEmail(
                agent_id=agent.id,
                gmail_message_id=message.gmail_message_id,
                gmail_thread_id=message.gmail_thread_id,
                alias=str(agent.email),
                sender_address=sender,
                sender_display_name=sender_display_name(message.from_header),
                subject=message.subject_text,
                message_id_header=message.message_id_header.strip(),
                references_header=message.references_header.strip(),
                body_text=body,
                received_at=received_at,
            ),
            needs_queued_reply=busy,
        )
        if inserted:
            logger.info(
                "Email queued: alias=%s agent_id=%s sender=%s "
                "gmail_message_id=%s busy=%s",
                agent.email,
                agent.id,
                sender,
                message.gmail_message_id,
                busy,
            )
            queued_for.append(agent.id)
            if on_queued is not None:
                on_queued(agent.id)
    return queued_for
