"""How an inbound email is presented to the agent."""

from __future__ import annotations

import time

from src.channels.email.inbound_store import InboundEmail


def frame_inbound_email(item: InboundEmail, user_folder: str) -> str:
    """The user-message text for one email: a header line, then the body."""
    received = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(item.received_at))
    subject = " ".join(item.subject.split()) or "(no subject)"
    body = item.body_text.strip() or "(empty message)"
    return (
        f"[Email from {item.sender_address}, user folder = {user_folder}, "
        f'subject "{subject}", received {received}]\n\n{body}'
    )
