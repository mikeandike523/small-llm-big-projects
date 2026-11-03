"""Sender authentication from Gmail's Authentication-Results header (RFC 8601).

The From header is trivially forged, so an allowlisted sender must also pass
DMARC as evaluated by Gmail's own receiving server. Only the *topmost*
Authentication-Results header is trusted, and only when Gmail
(``mx.google.com``) wrote it: headers further down were present before the
message reached Gmail and can be planted by the sender.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.email_addresses import ascii_lower

GOOGLE_AUTHSERV_ID = "mx.google.com"

_DMARC_RE = re.compile(r"(?:^|;)\s*dmarc\s*=\s*([a-z]+)", re.IGNORECASE)
_HEADER_FROM_RE = re.compile(r"header\.from\s*=\s*([^\s;()]+)", re.IGNORECASE)


@dataclass(frozen=True)
class AuthVerdict:
    passed: bool
    reason: str


def _strip_comments(value: str) -> str:
    """Drop RFC 5322 (comments), which may contain look-alike key=value text."""
    out: list[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def evaluate_sender_authentication(
    authentication_results: tuple[str, ...], sender_address: str
) -> AuthVerdict:
    """Pass only when Gmail's own result says dmarc=pass for the sender's domain."""
    if not authentication_results:
        return AuthVerdict(False, "no Authentication-Results header")
    top = _strip_comments(authentication_results[0])
    authserv_id = ascii_lower(top.split(";", 1)[0].strip())
    if authserv_id != GOOGLE_AUTHSERV_ID:
        return AuthVerdict(
            False, f"topmost Authentication-Results is not from {GOOGLE_AUTHSERV_ID}"
        )
    dmarc = _DMARC_RE.search(top)
    if dmarc is None:
        return AuthVerdict(False, "no DMARC result (sender domain may lack DMARC)")
    if ascii_lower(dmarc.group(1)) != "pass":
        return AuthVerdict(False, f"dmarc={ascii_lower(dmarc.group(1))}")
    dmarc_clause = top[dmarc.start(1) :].split(";", 1)[0]
    header_from = _HEADER_FROM_RE.search(dmarc_clause)
    sender_domain = sender_address.rsplit("@", 1)[-1]
    if header_from is None or ascii_lower(header_from.group(1)) != sender_domain:
        return AuthVerdict(False, "DMARC result does not match the sender's domain")
    return AuthVerdict(True, "dmarc=pass")
