"""Inbound-alias classification without session side effects."""

from __future__ import annotations

from dataclasses import replace
from email.utils import getaddresses

from src.channels.email.mime import ParsedGmailMessage


def classify_alias_message(
    message: ParsedGmailMessage, alias_email: str
) -> ParsedGmailMessage:
    if message.direction == "outbound":
        return replace(
            message, relevant_to_alias=False, alias_match_reason="sent-label"
        )
    expected = alias_email.casefold()
    candidates = (
        ("to", message.to_header),
        ("cc", message.cc_header),
        ("delivered-to", message.delivered_to_header),
        ("x-original-to", message.original_to_header),
    )
    for source, raw in candidates:
        addresses = {address.casefold() for _name, address in getaddresses([raw])}
        if expected in addresses:
            return replace(message, relevant_to_alias=True, alias_match_reason=source)
    return replace(
        message, relevant_to_alias=False, alias_match_reason="no-alias-header"
    )
