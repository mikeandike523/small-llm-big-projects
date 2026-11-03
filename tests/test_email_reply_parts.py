from __future__ import annotations

from email import message_from_bytes
from email.policy import default

from src.channels.email.auth_results import evaluate_sender_authentication
from src.channels.email.config import EmailConfig
from src.channels.email.inbound_store import InboundEmail
from src.channels.email.outbound import (
    build_final_reply,
    build_status_reply,
    markdown_to_html,
    reply_references,
    reply_subject,
)
from src.channels.email.quote_strip import strip_trailing_quote

GOOD_AUTH = (
    "mx.google.com; dkim=pass header.i=@example.test header.s=s1; "
    "spf=pass (google.com: domain of person@example.test designates 1.2.3.4) "
    "smtp.mailfrom=person@example.test; "
    "dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=example.test"
)


def _config() -> EmailConfig:
    return EmailConfig(
        mailbox_email="mailbox@example.test",
        system_alias_address="system@example.test",
        system_alias_name="Example System",
        project_id="example-project",
        processor_service_account_email="processor@example.test",
        topic_resource="projects/example-project/topics/gmail",
        subscription_resource="projects/example-project/subscriptions/gmail",
        push_service_account_email="push@example.test",
        push_audience="https://agent.example.test/webhooks/gmail",
    )


def _anchor(**overrides) -> InboundEmail:
    values = dict(
        id=7,
        session_id="s1",
        gmail_message_id="m1",
        gmail_thread_id="t1",
        alias="agent@example.test",
        sender_address="person@example.test",
        subject="Quarterly report",
        message_id_header="<parent@mail.example.test>",
        references_header="<root@mail.example.test> <mid@mail.example.test>",
        body_text="hello",
        received_at=1000.0,
        status="running",
        needs_queued_reply=False,
        queued_reply_sent_at=None,
        working_reply_sent_at=None,
        final_reply_sent_at=None,
        final_text=None,
        error_detail=None,
    )
    values.update(overrides)
    return InboundEmail(**values)


def _parse(message):
    return message_from_bytes(message.as_bytes(), policy=default)


# -- authentication ----------------------------------------------------------


def test_dmarc_pass_from_google_for_sender_domain_passes() -> None:
    verdict = evaluate_sender_authentication((GOOD_AUTH,), "person@example.test")
    assert verdict.passed


def test_only_the_topmost_header_is_trusted() -> None:
    forged_lower = (
        "relay.example.test; dmarc=fail header.from=example.test",
        GOOD_AUTH,
    )
    assert not evaluate_sender_authentication(
        forged_lower, "person@example.test"
    ).passed


def test_dmarc_fail_none_or_missing_is_rejected() -> None:
    for header in (
        "mx.google.com; dmarc=fail (p=NONE) header.from=example.test",
        "mx.google.com; spf=pass smtp.mailfrom=person@example.test",
    ):
        assert not evaluate_sender_authentication(
            (header,), "person@example.test"
        ).passed
    assert not evaluate_sender_authentication((), "person@example.test").passed


def test_dmarc_for_another_domain_is_rejected() -> None:
    assert not evaluate_sender_authentication((GOOD_AUTH,), "person@other.test").passed


def test_dmarc_text_inside_a_comment_is_ignored() -> None:
    header = "mx.google.com; spf=pass (dmarc=pass header.from=example.test)"
    assert not evaluate_sender_authentication((header,), "person@example.test").passed


# -- quote stripping ---------------------------------------------------------


def test_gmail_style_attribution_and_quote_is_stripped() -> None:
    text = (
        "Thanks, one more thing.\n\n"
        "On Mon, Nov 3, 2026 at 10:00 AM Agent <agent@example.test>\n"
        "wrote:\n\n> Earlier answer\n> more\n"
    )
    assert strip_trailing_quote(text) == "Thanks, one more thing."


def test_outlook_header_block_is_stripped() -> None:
    text = (
        "New question here\n\n________________________________\n"
        "From: Agent <agent@example.test>\nSent: Monday\n"
        "To: Person\nSubject: Re: thing\n\nold answer text\n"
    )
    assert strip_trailing_quote(text) == "New question here"


def test_inline_replies_between_quotes_are_kept_whole() -> None:
    text = (
        "On Mon, someone wrote:\n> question one\nmy answer one\n"
        "> question two\nmy answer two\n"
    )
    assert strip_trailing_quote(text) == text


def test_previously_sent_answer_is_stripped_without_markers() -> None:
    sent = "Here is the full quarterly summary you asked for, with numbers."
    text = f"Can you shorten it?\n\n{sent}\n"
    assert strip_trailing_quote(text, [sent]) == "Can you shorten it?"


def test_no_marker_returns_full_text_and_all_quote_is_kept() -> None:
    assert strip_trailing_quote("plain message") == "plain message"
    only_quote = "On Mon, A wrote:\n> hi\n"
    assert strip_trailing_quote(only_quote) == only_quote


# -- outbound headers --------------------------------------------------------


def test_reply_subject_never_stacks_re() -> None:
    assert reply_subject("Quarterly  report") == "Re: Quarterly report"
    assert reply_subject("RE: Quarterly report") == "RE: Quarterly report"
    assert reply_subject("") == "Re: (no subject)"


def test_references_append_parent_and_trim() -> None:
    assert reply_references("<a@x> <b@x>", "<c@x>") == "<a@x> <b@x> <c@x>"
    many = " ".join(f"<{i}@x>" for i in range(30))
    trimmed = reply_references(many, "<parent@x>").split()
    assert len(trimmed) == 20
    assert trimmed[0] == "<0@x>" and trimmed[-1] == "<parent@x>"


def test_status_reply_comes_from_system_alias_with_reply_to_alias() -> None:
    parsed = _parse(build_status_reply(_anchor(), _config(), "[Helper is working...]"))
    assert parsed["From"] == "Example System <system@example.test>"
    assert parsed["Reply-To"] == "agent@example.test"
    assert parsed["To"] == "person@example.test"
    assert parsed["In-Reply-To"] == "<parent@mail.example.test>"
    assert parsed["References"] == (
        "<root@mail.example.test> <mid@mail.example.test> " "<parent@mail.example.test>"
    )
    assert parsed["Subject"] == "Re: Quarterly report"
    assert parsed["Auto-Submitted"] == "auto-replied"
    assert parsed.get_content().strip() == "[Helper is working...]"


def test_final_reply_is_multipart_markdown_source_plus_html() -> None:
    answer = "# Title\n\n**bold** <script>alert(1)</script>"
    parsed = _parse(build_final_reply(_anchor(), "Helper", answer))
    assert parsed["From"] == "Helper <agent@example.test>"
    assert parsed["Reply-To"] is None
    assert parsed.get_content_type() == "multipart/alternative"
    plain = parsed.get_body(("plain",)).get_content()
    html = parsed.get_body(("html",)).get_content()
    # SMTP wire format uses CRLF; the text is otherwise the unchanged source.
    assert plain.replace("\r\n", "\n").strip() == answer
    assert "<h1>Title</h1>" in html and "<strong>bold</strong>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_markdown_raw_html_is_escaped() -> None:
    assert "<b>" not in markdown_to_html("<b>x</b>")
