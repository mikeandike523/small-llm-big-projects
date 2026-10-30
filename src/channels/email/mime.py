"""Gmail message normalization for durable debug display."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from email.header import decode_header, make_header
from typing import Any

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ParsedGmailMessage:
    gmail_message_id: str
    gmail_thread_id: str
    gmail_history_id: str | None
    internal_date_ms: int
    direction: str
    subject_text: str
    from_header: str
    to_header: str
    cc_header: str
    delivered_to_header: str
    original_to_header: str
    message_id_header: str
    in_reply_to_header: str
    references_header: str
    snippet: str
    text_body: str
    html_body: str
    labels: list[str]
    attachments: list[dict[str, Any]]
    relevant_to_alias: bool = False
    alias_match_reason: str | None = None


def _decode_b64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _decode_text(data: str, charset: str | None) -> str:
    raw = _decode_b64url(data)
    for encoding in (charset, "utf-8", "latin-1"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _header_value(headers: list[dict], name: str) -> str:
    values = [
        str(item.get("value") or "")
        for item in headers
        if str(item.get("name") or "").casefold() == name.casefold()
    ]
    value = ", ".join(item for item in values if item)
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError):
        return value


def _walk_parts(
    part: dict, text_parts: list[str], html_parts: list[str], attachments: list[dict]
) -> None:
    mime_type = str(part.get("mimeType") or "").casefold()
    filename = str(part.get("filename") or "")
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId")
    if filename or attachment_id:
        attachments.append(
            {
                "filename": filename,
                "mime_type": mime_type,
                "size": int(body.get("size") or 0),
                "attachment_id": str(attachment_id or ""),
            }
        )
    data = body.get("data")
    headers = part.get("headers") or []
    content_type = _header_value(headers, "Content-Type")
    charset = None
    charset_match = re.search(
        r"charset\s*=\s*[\"']?([^;\"']+)", content_type, re.IGNORECASE
    )
    if charset_match:
        charset = charset_match.group(1).strip()
    is_attachment = bool(filename or attachment_id)
    if data and mime_type == "text/plain" and not is_attachment:
        text_parts.append(_decode_text(str(data), charset))
    elif data and mime_type == "text/html" and not is_attachment:
        html_parts.append(_decode_text(str(data), charset))
    for child in part.get("parts") or []:
        _walk_parts(child, text_parts, html_parts, attachments)


def parse_gmail_message(message: dict) -> ParsedGmailMessage:
    payload = message.get("payload") or {}
    headers = payload.get("headers") or []
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict] = []
    _walk_parts(payload, text_parts, html_parts, attachments)
    html_body = "\n".join(part for part in html_parts if part)
    text_body = "\n".join(part for part in text_parts if part)
    if not text_body and html_body:
        text_body = BeautifulSoup(html_body, "html.parser").get_text("\n")
    labels = [str(value) for value in message.get("labelIds") or []]
    return ParsedGmailMessage(
        gmail_message_id=str(message["id"]),
        gmail_thread_id=str(message["threadId"]),
        gmail_history_id=(
            str(message["historyId"]) if message.get("historyId") else None
        ),
        internal_date_ms=int(message.get("internalDate") or 0),
        direction="outbound" if "SENT" in labels else "inbound",
        subject_text=_header_value(headers, "Subject"),
        from_header=_header_value(headers, "From"),
        to_header=_header_value(headers, "To"),
        cc_header=_header_value(headers, "Cc"),
        delivered_to_header=_header_value(headers, "Delivered-To"),
        original_to_header=_header_value(headers, "X-Original-To"),
        message_id_header=_header_value(headers, "Message-ID"),
        in_reply_to_header=_header_value(headers, "In-Reply-To"),
        references_header=_header_value(headers, "References"),
        snippet=str(message.get("snippet") or ""),
        text_body=text_body,
        html_body=html_body,
        labels=labels,
        attachments=attachments,
    )
