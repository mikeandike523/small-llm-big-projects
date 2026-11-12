"""Emails a session starts itself (the ``send_email`` tool).

Each one starts a NEW Gmail thread. The conversation thread mirrors the
session's turns (one user email in, one final answer out), and only the runner
writes to it, so the agent never posts there.

A reply needs no special handling: it reaches the session's address, and the
router treats it like any other email. In a pool, a new thread means a new
conversation, so an allowlisted recipient's reply starts a new session. A
single session owns its alias, so the reply lands in that session. Replies from
people not on the allowlist are dropped as usual; the optional no-reply note
tells such recipients so.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

from src.channels.email.outbound import markdown_to_html

NOREPLY_NOTE_PARAM = "system.channels.email.add-noreply-note"
NOREPLY_NOTE = (
    "_This address is not monitored, so replies to this email will not be read._"
)
SUBJECT_MAX_CHARS = 200


@dataclass(frozen=True)
class SendIdentity:
    """Who a session's emails come from, and whose replies it answers."""

    address: str
    name: str
    allowed_senders: frozenset[str]
    # A pool answers each thread in its own session; a single session answers
    # every thread itself.
    is_pool: bool


def send_identity(
    agent: Any | None, email_settings: dict | None
) -> SendIdentity | None:
    """The session's sending identity, or None when it may not send email.

    ``agent`` is the pool's agent (None for a single session). A pool agent must
    be active (not retired) and enabled; a single session needs its email channel
    on and an alias claimed.
    """
    if agent is not None:
        if (
            agent.is_retired
            or not agent.enabled
            or not agent.email
            or agent.registered_at is None
        ):
            return None
        return SendIdentity(
            address=str(agent.email),
            name=agent.name or "",
            allowed_senders=frozenset(agent.allowed_senders),
            is_pool=True,
        )
    settings = email_settings or {}
    alias = str(settings.get("alias") or "")
    if not settings.get("enabled") or not alias:
        return None
    return SendIdentity(
        address=alias,
        name=str(settings.get("agent_name") or "").strip(),
        allowed_senders=frozenset(settings.get("allowed_senders") or []),
        is_pool=False,
    )


def session_send_identity(session_id: str, agent_id: str | None) -> SendIdentity | None:
    """``send_identity`` for one session, read live; None while email is not running."""
    from src.channels.email import get_email_config

    if get_email_config() is None:
        return None
    if agent_id:
        from src.utils.agent_store import get_agent

        agent = get_agent(agent_id)
        return send_identity(agent, None) if agent is not None else None
    from src.channels.email.router import email_settings_for

    return send_identity(None, email_settings_for(session_id))


def clean_subject(subject: str) -> str:
    """One line (a header cannot hold line breaks), trimmed to a sane length."""
    return " ".join((subject or "").split())[:SUBJECT_MAX_CHARS]


def build_new_email(
    identity: SendIdentity,
    recipient: str,
    subject: str,
    body_markdown: str,
    *,
    add_noreply_note: bool,
) -> EmailMessage:
    """A new email (no In-Reply-To or References): Markdown text plus HTML."""
    body = (body_markdown or "").rstrip()
    if add_noreply_note:
        body = f"{body}\n\n{NOREPLY_NOTE}" if body else NOREPLY_NOTE
    message = EmailMessage(policy=SMTP)
    message["From"] = (
        formataddr((identity.name, identity.address))
        if identity.name
        else identity.address
    )
    message["To"] = recipient
    message["Subject"] = clean_subject(subject) or "(no subject)"
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=identity.address.rsplit("@", 1)[-1])
    # Written by an agent, not a person: auto-responders should not answer it
    # (RFC 3834). The recipient's own replies are unaffected.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(body)
    message.add_alternative(markdown_to_html(body), subtype="html")
    return message


@dataclass(frozen=True)
class SentEmail:
    gmail_message_id: str
    gmail_thread_id: str
    noreply_note_added: bool
    replies_answered: bool


def send_new_email(
    gmail: Any,
    identity: SendIdentity,
    recipient: str,
    subject: str,
    body_markdown: str,
    *,
    noreply_note_enabled: bool,
) -> SentEmail:
    """Send it in a new thread (no ``threadId``); Gmail errors propagate."""
    import base64

    answered = recipient in identity.allowed_senders
    add_note = noreply_note_enabled and not answered
    message = build_new_email(
        identity, recipient, subject, body_markdown, add_noreply_note=add_note
    )
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    return SentEmail(
        gmail_message_id=str(sent.get("id") or ""),
        gmail_thread_id=str(sent.get("threadId") or ""),
        noreply_note_added=add_note,
        replies_answered=answered,
    )


def build_send_client() -> Any:
    """A fresh client per send: Google API clients are not thread-safe, and the
    runner's client lives on the runner thread."""
    from src.channels.email import get_email_config
    from src.channels.email.gmail_client import build_gmail_client

    config = get_email_config()
    if config is None:
        raise RuntimeError("The email channel is not running.")
    return build_gmail_client(config)
