"""Inbound routing: decide who (if anyone) should handle an email.

An address belongs to one owner: an agent, whose pool answers each conversation
in its own session, or a single session holding it as an alias.

Runs during history sync for messages relevant to a claimed address. It only
writes queue rows; it never sends mail (sync holds a lease, and sending is the
runner's job) and never creates a session, so dropped mail spawns nothing.
Drop rules, in order:

1. our own / outbound mail;
2. auto-generated mail (``Auto-Submitted`` other than ``no``, bulk/list
   ``Precedence``) -- prevents auto-responder loops;
3. no recipient header names a claimed address -> silent (the mailbox is shared
   with unrelated automation);
4. per owner: disabled, or Gmail received the message before the address was
   claimed;
5. sender not on the owner's allowlist, or failing DMARC -> WARNING log
   "Possible malicious/unknown email".
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import timezone
from email.utils import parseaddr, parsedate_to_datetime

from src.channels.email.auth_results import evaluate_sender_authentication
from src.channels.email.filtering import recipient_addresses
from src.channels.email.inbound_store import (
    NewInboundEmail,
    conversation_has_unfinished_work,
    has_unfinished_work,
    insert_inbound,
    sent_final_texts,
    sent_final_texts_for_session,
)
from src.channels.email.mime import ParsedGmailMessage
from src.channels.email.quote_strip import strip_trailing_quote
from src.utils.email_addresses import ascii_lower, header_sender_address
from src.utils.email_settings import normalize_email_settings
from src.utils.session_events import EVT_EMAIL_SETTINGS_SET
from src.utils.sql.agents_db import load_agents_for_emails
from src.utils.sql.email_alias_db import list_alias_claims
from src.utils.sql.session_store_db import load_latest_event_payload

logger = logging.getLogger(__name__)

_AUTOMATED_PRECEDENCE = {"bulk", "junk", "list", "auto_reply"}
_DISPLAY_NAME_MAX_CHARS = 255
# A sent date further before Gmail's accepted time than this is a bad clock or
# backdating, not mail that was merely slow to arrive.
_MAX_SENT_DATE_LEAD_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class _Route:
    """One owner of an address the message was sent to."""

    alias: str
    enabled: bool
    claimed_at: float | None
    allowed_senders: frozenset[str]
    agent_id: str | None = None
    session_id: str | None = None

    @property
    def owner_id(self) -> str:
        return str(self.agent_id or self.session_id)

    @property
    def owner_label(self) -> str:
        if self.agent_id is not None:
            return f"agent_id={self.agent_id}"
        return f"session_id={self.session_id}"


def email_settings_for(session_id: str) -> dict:
    """One session's email settings without rebuilding the session.

    Live in-process settings win; otherwise the newest persisted settings event
    is authoritative (same as heartbeat).
    """
    from src.ui_connector.socket_handler_components import runtime_settings

    live = runtime_settings.peek(session_id)
    if live is not None:
        return live.email_settings
    payload = load_latest_event_payload(session_id, EVT_EMAIL_SETTINGS_SET)
    return normalize_email_settings((payload or {}).get("settings"))


def _session_is_busy(session_id: str) -> bool:
    from src.ui_connector.socket_handler_components.state import (
        reserved_turn_origin,
    )

    return reserved_turn_origin(session_id) is not None or has_unfinished_work(
        session_id
    )


def _routes_for(recipients: Collection[str]) -> list[_Route]:
    routes = [
        _Route(
            alias=str(agent.email),
            enabled=agent.enabled,
            claimed_at=agent.registered_at,
            allowed_senders=frozenset(agent.allowed_senders),
            agent_id=agent.id,
        )
        for agent in load_agents_for_emails(recipients)
    ]
    for claim in list_alias_claims(recipients):
        settings = email_settings_for(claim.session_id)
        routes.append(
            _Route(
                alias=claim.alias,
                enabled=claim.enabled,
                claimed_at=claim.claimed_at,
                allowed_senders=frozenset(settings.get("allowed_senders") or []),
                session_id=claim.session_id,
            )
        )
    return routes


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


def email_sent_time(date_header: str, received_at: float) -> float:
    """When the sender sent the email, for ordering the queue.

    The ``Date`` header says when, but the sender controls it. ``received_at``
    is Gmail's accepted time, which the sender cannot set, so it bounds the
    header and stands in when the header cannot be used.
    """
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        sent_at = parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return received_at
    if sent_at < received_at - _MAX_SENT_DATE_LEAD_SECONDS:
        return received_at
    return min(sent_at, received_at)


def _log_unknown(sender: str | None, raw_from: str, route: _Route, reason: str):
    logger.warning(
        "Possible malicious/unknown email: sender=%s from_header=%r alias=%s "
        "%s time=%s reason=%s",
        sender or "(unparseable)",
        raw_from,
        route.alias,
        route.owner_label,
        time.strftime("%Y-%m-%d %H:%M:%S %z"),
        reason,
    )


def route_inbound_message(
    message: ParsedGmailMessage,
    *,
    on_queued: Callable[[str], None] | None = None,
) -> list[str]:
    """Queue the message for every owner that should answer it.

    Returns the agent or session ids that newly queued it (redelivery queues
    nothing).
    """
    if message.direction == "outbound" or "SENT" in message.labels:
        return []
    if is_automated_message(message):
        logger.info(
            "Email ignored (automated message): gmail_message_id=%s",
            message.gmail_message_id,
        )
        return []
    routes = _routes_for(recipient_addresses(message))
    if not routes:
        return []

    sender = header_sender_address(message.from_header)
    received_at = message.internal_date_ms / 1000.0
    queued_for: list[str] = []
    for route in routes:
        if not route.enabled:
            logger.info(
                "Email ignored (disabled): alias=%s %s gmail_message_id=%s",
                route.alias,
                route.owner_label,
                message.gmail_message_id,
            )
            continue
        if route.claimed_at is None or received_at < route.claimed_at:
            logger.info(
                "Email ignored (received before the address was claimed): "
                "alias=%s %s gmail_message_id=%s",
                route.alias,
                route.owner_label,
                message.gmail_message_id,
            )
            continue
        if sender is None or sender not in route.allowed_senders:
            _log_unknown(sender, message.from_header, route, "sender not allowed")
            continue
        verdict = evaluate_sender_authentication(message.authentication_results, sender)
        if not verdict.passed:
            _log_unknown(sender, message.from_header, route, verdict.reason)
            continue

        if route.agent_id is not None:
            earlier_answers = sent_final_texts(
                route.agent_id, message.gmail_thread_id, sender
            )
            busy = conversation_has_unfinished_work(
                route.agent_id, message.gmail_thread_id, sender
            )
        else:
            session_id = str(route.session_id)
            earlier_answers = sent_final_texts_for_session(
                session_id, message.gmail_thread_id
            )
            busy = _session_is_busy(session_id)
        inserted = insert_inbound(
            NewInboundEmail(
                agent_id=route.agent_id,
                session_id=route.session_id,
                gmail_message_id=message.gmail_message_id,
                gmail_thread_id=message.gmail_thread_id,
                alias=route.alias,
                sender_address=sender,
                sender_display_name=sender_display_name(message.from_header),
                subject=message.subject_text,
                message_id_header=message.message_id_header.strip(),
                references_header=message.references_header.strip(),
                body_text=strip_trailing_quote(message.text_body, earlier_answers),
                received_at=received_at,
                sent_at=email_sent_time(message.date_header, received_at),
            ),
            needs_queued_reply=busy,
        )
        if inserted:
            logger.info(
                "Email queued: alias=%s %s sender=%s gmail_message_id=%s busy=%s",
                route.alias,
                route.owner_label,
                sender,
                message.gmail_message_id,
                busy,
            )
            queued_for.append(route.owner_id)
            if on_queued is not None:
                on_queued(route.owner_id)
    return queued_for
