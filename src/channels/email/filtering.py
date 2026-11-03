"""Inbound-alias classification without session side effects."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace

from src.utils.email_addresses import header_addresses
from src.channels.email.mime import ParsedGmailMessage


def recipient_header_sources(
    message: ParsedGmailMessage,
) -> tuple[tuple[str, str], ...]:
    """Every header that can name the alias a message was delivered for."""
    return (
        ("to", message.to_header),
        ("cc", message.cc_header),
        ("delivered-to", message.delivered_to_header),
        ("x-original-to", message.original_to_header),
    )


def recipient_addresses(message: ParsedGmailMessage) -> set[str]:
    """Normalized addresses from all recipient headers (invalid ones dropped)."""
    return header_addresses(
        *(raw for _source, raw in recipient_header_sources(message))
    )


def classify_alias_message(
    message: ParsedGmailMessage, aliases: Collection[str]
) -> ParsedGmailMessage:
    """Flag a message as relevant when any recipient header names a claimed alias.

    ``aliases`` must already be normalized (see ``addresses.parse_email_address``).
    """
    if message.direction == "outbound":
        return replace(
            message, relevant_to_alias=False, alias_match_reason="sent-label"
        )
    expected = set(aliases)
    if expected:
        for source, raw in recipient_header_sources(message):
            if header_addresses(raw) & expected:
                return replace(
                    message, relevant_to_alias=True, alias_match_reason=source
                )
    return replace(
        message, relevant_to_alias=False, alias_match_reason="no-alias-header"
    )
