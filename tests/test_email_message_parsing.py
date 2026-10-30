from __future__ import annotations

import base64

from src.channels.email.filtering import classify_alias_message
from src.channels.email.mime import parse_gmail_message


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_parse_and_classify_inbound_alias_message() -> None:
    raw = {
        "id": "message-1",
        "threadId": "thread-1",
        "historyId": "99",
        "internalDate": "1234",
        "labelIds": ["INBOX"],
        "snippet": "hello",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Example"},
                {"name": "From", "value": "Person <person@example.test>"},
                {"name": "To", "value": "Assistant <assistant@example.test>"},
            ],
            "body": {"data": _encoded("Full body")},
        },
    }
    parsed = classify_alias_message(parse_gmail_message(raw), "assistant@example.test")
    assert parsed.text_body == "Full body"
    assert parsed.relevant_to_alias is True
    assert parsed.alias_match_reason == "to"


def test_sent_message_is_not_treated_as_new_inbound_work() -> None:
    raw = {
        "id": "message-2",
        "threadId": "thread-1",
        "internalDate": "1235",
        "labelIds": ["SENT"],
        "payload": {"headers": [], "body": {}},
    }
    parsed = classify_alias_message(parse_gmail_message(raw), "assistant@example.test")
    assert parsed.direction == "outbound"
    assert parsed.relevant_to_alias is False
