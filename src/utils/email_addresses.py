"""Predictable, ASCII-only email address normalization.

Every place that compares addresses (session alias claims, sender
allowlists, inbound recipient/sender matching) goes through this module so
the rules never drift. Non-ASCII input is rejected outright *before* any case
change: Unicode case mapping (``str.casefold``/``str.lower`` on arbitrary
text) can turn look-alike characters into something that compares equal to
a legitimate address. Internationalized domains must be entered in their
ASCII ``xn--`` form.
"""

from __future__ import annotations

import re
from email.utils import getaddresses, parseaddr

_ASCII_UPPER_TO_LOWER = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)
# Printable ASCII without space (0x21-0x7E).
_PRINTABLE_ASCII_NO_SPACE = re.compile(r"^[\x21-\x7e]+$")
_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_ADDRESS_LENGTH = 320


class InvalidEmailAddressError(ValueError):
    """The value is not an acceptable email address; ``str(exc)`` says why."""


def ascii_lower(value: str) -> str:
    """Lowercase A-Z only; every other character is left untouched."""
    return value.translate(_ASCII_UPPER_TO_LOWER)


def parse_email_address(raw: str) -> str:
    """Return the normalized (trimmed, ASCII-lowercased) address or raise."""
    if not isinstance(raw, str):
        raise InvalidEmailAddressError("must be a string")
    value = raw.strip()
    if not value:
        raise InvalidEmailAddressError("is empty")
    if len(value) > _MAX_ADDRESS_LENGTH:
        raise InvalidEmailAddressError(
            f"is longer than {_MAX_ADDRESS_LENGTH} characters"
        )
    if not value.isascii():
        raise InvalidEmailAddressError(
            "contains non-ASCII characters (use the xn-- form for "
            "international domains)"
        )
    if not _PRINTABLE_ASCII_NO_SPACE.match(value):
        raise InvalidEmailAddressError("contains whitespace or control characters")
    if value.count("@") != 1:
        raise InvalidEmailAddressError("must contain exactly one '@'")
    local, domain = value.split("@")
    if not local:
        raise InvalidEmailAddressError("is missing the part before '@'")
    if any(ch in local for ch in '<>()[]\\,;:"'):
        raise InvalidEmailAddressError("has characters not allowed before '@'")
    domain = ascii_lower(domain)
    labels = domain.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL.match(label) for label in labels):
        raise InvalidEmailAddressError("has an invalid domain")
    return f"{ascii_lower(local)}@{domain}"


def normalize_email_address(raw: str) -> str | None:
    """Same rules as :func:`parse_email_address`; None when invalid."""
    try:
        return parse_email_address(raw)
    except InvalidEmailAddressError:
        return None


def header_sender_address(from_header: str) -> str | None:
    """Normalized addr-spec of a From header; the display name is ignored."""
    _name, address = parseaddr(from_header or "")
    return normalize_email_address(address) if address else None


def header_addresses(*raw_headers: str) -> set[str]:
    """Every valid normalized address found in the given address headers."""
    found: set[str] = set()
    for raw in raw_headers:
        # One header per call, and never an empty one: Python's strict
        # getaddresses() discards *every* address when the joined input looks
        # malformed (e.g. "a@x, , "), which would silently drop recipients.
        if not (raw or "").strip():
            continue
        for _name, address in getaddresses([raw]):
            normalized = normalize_email_address(address) if address else None
            if normalized is not None:
                found.add(normalized)
    return found
