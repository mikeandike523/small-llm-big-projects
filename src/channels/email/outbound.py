"""Threaded email replies anchored on the user's email (one queue row).

Every reply about an inbound email -- queued / working / error / cancelled
status notes and the final answer -- is built only from that email's stored
headers, so no shared reply-chain state exists and concurrent replies cannot
race:

    In-Reply-To: <its Message-ID>
    References:  <its References> <its Message-ID>
    Subject:     Re: <its subject>          (no stacked "Re:")
    threadId:    its Gmail thread           (Gmail API parameter)

Replies go only to the (allowlisted, DMARC-checked) sender; the inbound
Reply-To/Cc are ignored. Status notes come from the system alias with
``Reply-To`` set to the session alias, so hitting Reply still reaches the
agent. Everything is marked ``Auto-Submitted: auto-replied`` (RFC 3834).

Every From address must be a registered Gmail Send-As address of the mailbox,
otherwise Gmail rewrites the From header to the mailbox's primary address.
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

from markdown_it import MarkdownIt

from src.channels.email.config import EmailConfig
from src.channels.email.inbound_store import InboundEmail

_RE_PREFIX = re.compile(r"^\s*re\s*:", re.IGNORECASE)
_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")
_MAX_REFERENCES = 20

_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
    ["table", "strikethrough"]
)

_HTML_TEMPLATE = (
    '<!doctype html><html><head><meta charset="utf-8"></head>'
    '<body style="font-family: -apple-system, Segoe UI, Roboto, Helvetica, '
    'Arial, sans-serif; font-size: 14px; line-height: 1.5;">{body}</body></html>'
)


def reply_subject(subject: str) -> str:
    clean = " ".join((subject or "").split())
    if not clean:
        return "Re: (no subject)"
    return clean if _RE_PREFIX.match(clean) else f"Re: {clean}"


def reply_references(references_header: str, message_id_header: str) -> str:
    """The parent's References plus its Message-ID, trimmed like RFC 5322 3.6.4."""
    ids = _MESSAGE_ID_RE.findall(references_header or "")
    parent = _MESSAGE_ID_RE.findall(message_id_header or "")
    if parent and parent[0] not in ids:
        ids.append(parent[0])
    if len(ids) > _MAX_REFERENCES:
        # Keep the thread root plus the most recent ancestors.
        ids = ids[:1] + ids[-(_MAX_REFERENCES - 1) :]
    return " ".join(ids)


def markdown_to_html(markdown_text: str) -> str:
    """Render the agent's Markdown; raw HTML in it is escaped, never passed."""
    return _HTML_TEMPLATE.format(body=_markdown.render(markdown_text or ""))


def _base_message(
    anchor: InboundEmail, *, from_name: str, from_address: str
) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["From"] = (
        formataddr((from_name, from_address)) if from_name else from_address
    )
    message["To"] = anchor.sender_address
    message["Subject"] = reply_subject(anchor.subject)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=from_address.rsplit("@", 1)[-1])
    parent = _MESSAGE_ID_RE.findall(anchor.message_id_header or "")
    if parent:
        message["In-Reply-To"] = parent[0]
    references = reply_references(anchor.references_header, anchor.message_id_header)
    if references:
        message["References"] = references
    message["Auto-Submitted"] = "auto-replied"
    return message


def build_status_reply(
    anchor: InboundEmail, config: EmailConfig, text: str
) -> EmailMessage:
    """A short plain-text status note from the system alias."""
    message = _base_message(
        anchor,
        from_name=config.system_alias_name,
        from_address=config.system_alias_address,
    )
    message["Reply-To"] = anchor.alias
    message.set_content(text)
    return message


def build_final_reply(
    anchor: InboundEmail, agent_name: str, answer_markdown: str
) -> EmailMessage:
    """The answer from the session alias: text = Markdown source, plus HTML."""
    message = _base_message(anchor, from_name=agent_name, from_address=anchor.alias)
    message.set_content(answer_markdown or "")
    message.add_alternative(markdown_to_html(answer_markdown), subtype="html")
    return message


def send_message(gmail: Any, anchor: InboundEmail, message: EmailMessage) -> dict:
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return (
        gmail.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": anchor.gmail_thread_id})
        .execute()
    )
