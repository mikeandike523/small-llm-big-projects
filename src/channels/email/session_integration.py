"""Explicit extension points for future SLBP session/email interaction.

These functions intentionally perform no database writes, session creation,
agent turns, or outgoing email. The debug ingestion path is safe to exercise
before those product decisions are implemented.
"""

from __future__ import annotations

from src.channels.email.mime import ParsedGmailMessage


def handle_inbound_email_stub(_message: ParsedGmailMessage) -> None:
    """Future: choose an existing session or create one, then submit the mail."""
    return


def send_session_reply_to_email_stub(
    _session_id: str, _reply_text: str, _source_message: ParsedGmailMessage
) -> None:
    """Future: turn a completed session response into a threaded Gmail reply."""
    return
