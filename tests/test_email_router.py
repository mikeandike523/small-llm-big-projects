from __future__ import annotations

import logging

import pytest

import src.channels.email.router as router
from src.channels.email.mime import ParsedGmailMessage
from src.utils.email_settings import DEFAULT_EMAIL_SETTINGS
from src.utils.sql.email_alias_db import AliasClaim

GOOD_AUTH = (
    "mx.google.com; dkim=pass header.i=@example.test; "
    "dmarc=pass (p=REJECT) header.from=example.test",
)


def _message(**overrides) -> ParsedGmailMessage:
    values = dict(
        gmail_message_id="m1",
        gmail_thread_id="t1",
        gmail_history_id="9",
        internal_date_ms=2_000_000,
        direction="inbound",
        subject_text="Hello",
        from_header="Person <Person@Example.test>",
        to_header="Agent <agent@example.test>",
        cc_header="",
        delivered_to_header="",
        original_to_header="",
        message_id_header="<m1@mail.example.test>",
        in_reply_to_header="",
        references_header="",
        snippet="",
        text_body="Please help",
        html_body="",
        labels=["INBOX"],
        attachments=[],
        relevant_to_alias=True,
        authentication_results=GOOD_AUTH,
    )
    values.update(overrides)
    return ParsedGmailMessage(**values)


def _claim(session_id="s1", alias="agent@example.test", **overrides) -> AliasClaim:
    values = dict(
        session_id=session_id,
        alias=alias,
        enabled=True,
        claimed_at=1000.0,
        created_at=1.0,
    )
    values.update(overrides)
    return AliasClaim(**values)


class Env:
    def __init__(self, monkeypatch, claims, *, senders=("person@example.test",)):
        self.claims = claims
        self.inserted: list = []
        self.busy = False
        self.settings = {**DEFAULT_EMAIL_SETTINGS, "allowed_senders": list(senders)}
        monkeypatch.setattr(
            router,
            "list_alias_claims",
            lambda aliases: [c for c in self.claims if c.alias in aliases],
        )
        monkeypatch.setattr(router, "email_settings_for", lambda _sid: self.settings)
        monkeypatch.setattr(router, "_session_is_busy", lambda _sid: self.busy)
        monkeypatch.setattr(router, "sent_final_texts", lambda *_a: [])
        monkeypatch.setattr(router, "insert_inbound", self._insert)

    def _insert(self, item, *, needs_queued_reply):
        self.inserted.append((item, needs_queued_reply))
        return True


def test_allowed_authenticated_mail_is_queued(monkeypatch) -> None:
    env = Env(monkeypatch, [_claim()])
    woken: list[str] = []
    assert router.route_inbound_message(_message(), on_queued=woken.append) == ["s1"]
    item, needs_queued_reply = env.inserted[0]
    assert item.sender_address == "person@example.test"
    assert item.alias == "agent@example.test"
    assert item.received_at == 2000.0
    assert needs_queued_reply is False
    assert woken == ["s1"]


def test_busy_session_marks_queued_reply(monkeypatch) -> None:
    env = Env(monkeypatch, [_claim()])
    env.busy = True
    router.route_inbound_message(_message())
    assert env.inserted[0][1] is True


def test_unclaimed_alias_is_ignored_silently(monkeypatch, caplog) -> None:
    env = Env(monkeypatch, [_claim(alias="other@example.test")])
    with caplog.at_level(logging.DEBUG):
        assert router.route_inbound_message(_message()) == []
    assert env.inserted == []
    assert caplog.text == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"direction": "outbound", "labels": ["SENT"]},
        {"auto_submitted_header": "auto-replied"},
        {"precedence_header": "Bulk"},
    ],
)
def test_own_and_automated_mail_is_dropped(monkeypatch, overrides) -> None:
    env = Env(monkeypatch, [_claim()])
    assert router.route_inbound_message(_message(**overrides)) == []
    assert env.inserted == []


def test_auto_submitted_no_is_a_normal_message(monkeypatch) -> None:
    Env(monkeypatch, [_claim()])
    assert router.route_inbound_message(_message(auto_submitted_header="no")) == ["s1"]


def test_disabled_or_before_claim_is_dropped(monkeypatch) -> None:
    env = Env(monkeypatch, [_claim(enabled=False)])
    assert router.route_inbound_message(_message()) == []
    env.claims = [_claim(claimed_at=5000.0)]
    assert router.route_inbound_message(_message()) == []
    assert env.inserted == []


@pytest.mark.parametrize(
    ("overrides", "senders", "reason"),
    [
        ({}, ("someone@example.test",), "sender not allowed"),
        ({}, (), "sender not allowed"),
        (
            {"authentication_results": ("mx.google.com; dmarc=fail",)},
            ("person@example.test",),
            "dmarc=fail",
        ),
    ],
)
def test_unknown_or_unauthenticated_sender_is_logged(
    monkeypatch, caplog, overrides, senders, reason
) -> None:
    env = Env(monkeypatch, [_claim()], senders=senders)
    with caplog.at_level(logging.WARNING):
        assert router.route_inbound_message(_message(**overrides)) == []
    assert env.inserted == []
    assert "Possible malicious/unknown email: sender=person@example.test" in caplog.text
    assert reason in caplog.text


def test_message_for_two_aliases_goes_to_both_sessions(monkeypatch) -> None:
    env = Env(
        monkeypatch,
        [_claim("s1", "agent@example.test"), _claim("s2", "second@example.test")],
    )
    message = _message(cc_header="second@example.test")
    assert sorted(router.route_inbound_message(message)) == ["s1", "s2"]
    assert len(env.inserted) == 2


def test_duplicate_claims_fall_back_to_the_earliest_session(monkeypatch) -> None:
    Env(monkeypatch, [_claim("old", created_at=1.0), _claim("new", created_at=2.0)])
    assert router.route_inbound_message(_message()) == ["old"]


def test_redelivery_queues_nothing(monkeypatch) -> None:
    env = Env(monkeypatch, [_claim()])
    monkeypatch.setattr(router, "insert_inbound", lambda *_a, **_k: False)
    assert router.route_inbound_message(_message()) == []
    assert env.inserted == []


def test_quoted_history_is_stripped_before_queueing(monkeypatch) -> None:
    env = Env(monkeypatch, [_claim()])
    body = "New question\n\nOn Mon, Agent <agent@example.test> wrote:\n> old\n"
    router.route_inbound_message(_message(text_body=body))
    assert env.inserted[0][0].body_text == "New question"
