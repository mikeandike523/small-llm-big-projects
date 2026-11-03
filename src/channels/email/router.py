"""Inbound routing: decide which sessions (if any) should handle an email.

Runs during history sync for messages relevant to a claimed alias. It only
writes queue rows; it never sends mail (sync holds a lease, and sending is
the runner's job). Drop rules, in order:

1. our own / outbound mail;
2. auto-generated mail (``Auto-Submitted`` other than ``no``, bulk/list
   ``Precedence``) -- prevents auto-responder loops;
3. no recipient header names a claimed alias -> silent (the mailbox is
   shared with unrelated automation);
4. per claiming session: email disabled, or Gmail received the message
   before the alias was claimed;
5. sender not on the session's allowlist, or failing DMARC -> WARNING log
   "Possible malicious/unknown email".
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.channels.email.auth_results import evaluate_sender_authentication
from src.channels.email.filtering import recipient_addresses
from src.channels.email.inbound_store import (
    NewInboundEmail,
    has_unfinished_work,
    insert_inbound,
    sent_final_texts,
)
from src.channels.email.mime import ParsedGmailMessage
from src.channels.email.quote_strip import strip_trailing_quote
from src.utils.email_addresses import ascii_lower, header_sender_address
from src.utils.email_settings import normalize_email_settings
from src.utils.session_events import EVT_EMAIL_SETTINGS_SET
from src.utils.sql.email_alias_db import AliasClaim, list_alias_claims
from src.utils.sql.session_store_db import load_latest_event_payload

logger = logging.getLogger(__name__)

_AUTOMATED_PRECEDENCE = {"bulk", "junk", "list", "auto_reply"}


def email_settings_for(session_id: str) -> dict:
    """One session's email settings without rebuilding the session.

    Live in-process settings win; otherwise the newest persisted
    ``email_settings_set`` event is authoritative (same as heartbeat).
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


def is_automated_message(message: ParsedGmailMessage) -> bool:
    auto_submitted = ascii_lower(message.auto_submitted_header.strip())
    if auto_submitted and auto_submitted.split(";", 1)[0].strip() != "no":
        return True
    return ascii_lower(message.precedence_header.strip()) in _AUTOMATED_PRECEDENCE


def _earliest_claim_per_alias(claims: list[AliasClaim]) -> list[AliasClaim]:
    """Fallback if the UNIQUE index ever failed: the earliest session wins."""
    chosen: dict[str, AliasClaim] = {}
    for claim in claims:  # already ordered by session created_at
        chosen.setdefault(claim.alias, claim)
    return list(chosen.values())


def _log_unknown(sender: str | None, raw_from: str, claim: AliasClaim, reason: str):
    logger.warning(
        "Possible malicious/unknown email: sender=%s from_header=%r alias=%s "
        "session_id=%s time=%s reason=%s",
        sender or "(unparseable)",
        raw_from,
        claim.alias,
        claim.session_id,
        time.strftime("%Y-%m-%d %H:%M:%S %z"),
        reason,
    )


def route_inbound_message(
    message: ParsedGmailMessage,
    *,
    on_queued: Callable[[str], None] | None = None,
) -> list[str]:
    """Queue the message for every session that should answer it.

    Returns the session ids that newly queued it (redelivery queues nothing).
    """
    if message.direction == "outbound" or "SENT" in message.labels:
        return []
    if is_automated_message(message):
        logger.info(
            "Email ignored (automated message): gmail_message_id=%s",
            message.gmail_message_id,
        )
        return []
    claims = _earliest_claim_per_alias(list_alias_claims(recipient_addresses(message)))
    if not claims:
        return []

    sender = header_sender_address(message.from_header)
    received_at = message.internal_date_ms / 1000.0
    queued_for: list[str] = []
    for claim in claims:
        if not claim.enabled:
            logger.info(
                "Email ignored (email disabled for session): alias=%s "
                "session_id=%s gmail_message_id=%s",
                claim.alias,
                claim.session_id,
                message.gmail_message_id,
            )
            continue
        if claim.claimed_at is None or received_at < claim.claimed_at:
            logger.info(
                "Email ignored (received before alias was claimed): alias=%s "
                "session_id=%s gmail_message_id=%s",
                claim.alias,
                claim.session_id,
                message.gmail_message_id,
            )
            continue
        settings = email_settings_for(claim.session_id)
        if sender is None or sender not in set(settings.get("allowed_senders") or []):
            _log_unknown(sender, message.from_header, claim, "sender not allowed")
            continue
        verdict = evaluate_sender_authentication(message.authentication_results, sender)
        if not verdict.passed:
            _log_unknown(sender, message.from_header, claim, verdict.reason)
            continue

        body = strip_trailing_quote(
            message.text_body,
            sent_final_texts(claim.session_id, message.gmail_thread_id),
        )
        busy = _session_is_busy(claim.session_id)
        inserted = insert_inbound(
            NewInboundEmail(
                session_id=claim.session_id,
                gmail_message_id=message.gmail_message_id,
                gmail_thread_id=message.gmail_thread_id,
                alias=claim.alias,
                sender_address=sender,
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
                "Email queued: alias=%s session_id=%s sender=%s "
                "gmail_message_id=%s busy=%s",
                claim.alias,
                claim.session_id,
                sender,
                message.gmail_message_id,
                busy,
            )
            queued_for.append(claim.session_id)
            if on_queued is not None:
                on_queued(claim.session_id)
    return queued_for
