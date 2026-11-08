from __future__ import annotations

import base64
from email import message_from_bytes
from email.policy import default

import pytest

from src.channels.email import new_email
from src.channels.email.new_email import (
    NOREPLY_NOTE,
    SendIdentity,
    build_new_email,
    send_identity,
    send_new_email,
)
from src.tools import ALL_TOOL_DEFINITIONS, _TOOL_MAP
from src.tools import send_email as tool
from src.utils.approval_modes import (
    APPROVAL_MODE_AUTO_ACCEPT_EDITS,
    APPROVAL_MODE_DEFAULT,
    APPROVAL_MODE_FULL_AUTO,
)
from src.utils.sql.agents_db import Agent

IDENTITY = SendIdentity(
    address="agent@example.test",
    name="Example Agent",
    allowed_senders=frozenset({"friend@example.test"}),
    is_pool=True,
)


def _agent(**overrides) -> Agent:
    values = dict(
        id="agent-1",
        slug="example-agent",
        name="Example Agent",
        email="agent@example.test",
        registered_at=1000.0,
        enabled=True,
        allowed_senders=("friend@example.test",),
        profile_name="default",
        approval_mode="default",
        automation_approval_policy="wait-for-human",
        created_at=900.0,
    )
    values.update(overrides)
    return Agent(**values)


class _FakeGmail:
    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self._fail = fail

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, *, userId: str, body: dict):
        assert userId == "me"
        self.sent.append(body)
        return self

    def execute(self) -> dict:
        if self._fail is not None:
            raise self._fail
        return {"id": "gmail-msg-1", "threadId": "gmail-thread-1"}


def _decoded(body: dict):
    return message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=default)


# -- identity ---------------------------------------------------------------


def test_pool_identity_comes_from_the_agent() -> None:
    identity = send_identity(_agent(), None)
    assert identity == SendIdentity(
        address="agent@example.test",
        name="Example Agent",
        allowed_senders=frozenset({"friend@example.test"}),
        is_pool=True,
    )


@pytest.mark.parametrize(
    "overrides",
    [{"enabled": False}, {"email": None}, {"registered_at": None}],
)
def test_pool_agent_without_a_working_address_cannot_send(overrides) -> None:
    assert send_identity(_agent(**overrides), None) is None


def test_single_session_identity_needs_email_on_and_an_alias() -> None:
    settings = {
        "enabled": True,
        "alias": "desk@example.test",
        "agent_name": " Desk ",
        "allowed_senders": ["boss@example.test"],
    }
    identity = send_identity(None, settings)
    assert identity == SendIdentity(
        address="desk@example.test",
        name="Desk",
        allowed_senders=frozenset({"boss@example.test"}),
        is_pool=False,
    )
    assert send_identity(None, {**settings, "enabled": False}) is None
    assert send_identity(None, {**settings, "alias": ""}) is None
    assert send_identity(None, None) is None


def test_no_identity_while_the_email_channel_is_not_running(monkeypatch) -> None:
    import src.channels.email as email_pkg

    monkeypatch.setattr(email_pkg, "get_email_config", lambda: None)
    assert new_email.session_send_identity("s1", "agent-1") is None


# -- message ----------------------------------------------------------------


def test_new_email_starts_a_thread_and_renders_markdown() -> None:
    message = build_new_email(
        IDENTITY,
        "someone@example.test",
        "Quarterly\nreport",
        "Hello **there**",
        add_noreply_note=False,
    )
    assert message["From"] == "Example Agent <agent@example.test>"
    assert message["To"] == "someone@example.test"
    assert message["Subject"] == "Quarterly report"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message["In-Reply-To"] is None
    assert message["References"] is None
    plain = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()
    assert "Hello **there**" in plain
    assert "<strong>there</strong>" in html
    assert NOREPLY_NOTE not in plain


def test_noreply_note_is_italic_and_last() -> None:
    message = build_new_email(
        IDENTITY, "someone@example.test", "Hi", "Body", add_noreply_note=True
    )
    plain = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()
    assert plain.rstrip().endswith(NOREPLY_NOTE)
    assert "<em>This address is not monitored" in html


@pytest.mark.parametrize(
    ("recipient", "param_on", "expect_note"),
    [
        ("stranger@example.test", True, True),
        ("stranger@example.test", False, False),
        ("friend@example.test", True, False),
    ],
)
def test_note_only_for_recipients_off_the_allowlist(
    recipient, param_on, expect_note
) -> None:
    gmail = _FakeGmail()
    sent = send_new_email(
        gmail, IDENTITY, recipient, "Hi", "Body", noreply_note_enabled=param_on
    )
    assert sent.noreply_note_added is expect_note
    assert sent.replies_answered is (recipient == "friend@example.test")
    assert sent.gmail_thread_id == "gmail-thread-1"
    (body,) = gmail.sent
    assert "threadId" not in body  # always a new thread
    plain = _decoded(body).get_body(("plain",)).get_content()
    assert (NOREPLY_NOTE in plain) is expect_note


# -- tool -------------------------------------------------------------------


def test_tool_is_registered() -> None:
    assert _TOOL_MAP["send_email"] is tool
    names = [d["function"]["name"] for d in ALL_TOOL_DEFINITIONS]
    assert "send_email" in names


@pytest.mark.parametrize(
    ("mode", "asks"),
    [
        (APPROVAL_MODE_DEFAULT, True),
        (APPROVAL_MODE_AUTO_ACCEPT_EDITS, True),
        (APPROVAL_MODE_FULL_AUTO, False),
    ],
)
def test_approval_like_a_write_but_not_an_edit(mode, asks) -> None:
    assert tool.needs_approval({}, None, {"approval_mode": mode}) is asks


def _defs_and_map():
    defs = [
        {"function": {"name": "send_email"}},
        {"function": {"name": "sleep"}},
    ]
    return defs, {"send_email": tool, "sleep": object()}


def test_filter_drops_the_tool_when_the_session_cannot_send(monkeypatch) -> None:
    monkeypatch.setattr(new_email, "session_send_identity", lambda *_: None)
    defs, tool_map = tool.filter_unavailable(*_defs_and_map(), "s1", None)
    assert [d["function"]["name"] for d in defs] == ["sleep"]
    assert set(tool_map) == {"sleep"}


def test_filter_keeps_the_tool_when_the_session_can_send(monkeypatch) -> None:
    monkeypatch.setattr(new_email, "session_send_identity", lambda *_: IDENTITY)
    defs, tool_map = tool.filter_unavailable(*_defs_and_map(), "s1", "agent-1")
    assert len(defs) == 2
    assert "send_email" in tool_map


@pytest.fixture
def wired(monkeypatch):
    gmail = _FakeGmail()
    state = {"identity": IDENTITY, "noreply": False, "gmail": gmail}
    monkeypatch.setattr(tool, "_agent_id_for", lambda _sid: "agent-1")
    monkeypatch.setattr(tool, "_read_noreply_param", lambda: state["noreply"])
    monkeypatch.setattr(
        new_email, "session_send_identity", lambda *_: state["identity"]
    )
    monkeypatch.setattr(new_email, "build_send_client", lambda: state["gmail"])
    return state


def _run(**args) -> str:
    full = {"to": "friend@example.test", "subject": "Hi", "body": "Hello", **args}
    return tool.execute(full, {}, {"session_id": "s1"})


def test_execute_sends_and_reports(wired) -> None:
    result = _run(to=" Friend@Example.TEST ")
    assert result.startswith('Email sent to friend@example.test with subject "Hi".')
    assert "separate conversation" in result
    (body,) = wired["gmail"].sent
    assert _decoded(body)["To"] == "friend@example.test"


def test_execute_single_session_reply_wording(wired) -> None:
    wired["identity"] = SendIdentity(
        address="desk@example.test",
        name="",
        allowed_senders=frozenset({"friend@example.test"}),
        is_pool=False,
    )
    assert "come back to this session" in _run()


def test_execute_reports_note_for_unlisted_recipient(wired) -> None:
    wired["noreply"] = True
    result = _run(to="stranger@example.test")
    assert "will not be answered" in result
    assert "not monitored was added" in result


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({"to": "not-an-address"}, "invalid recipient"),
        ({"subject": "  \n "}, "subject is empty"),
        ({"body": "   "}, "body is empty"),
        ({"to": "agent@example.test"}, "your own address"),
    ],
)
def test_execute_rejects_bad_input(wired, args, error) -> None:
    result = _run(**args)
    assert result.startswith("Error:") and error in result
    assert wired["gmail"].sent == []


def test_execute_refuses_when_email_was_turned_off(wired) -> None:
    wired["identity"] = None
    assert "cannot send email" in _run()
    assert wired["gmail"].sent == []


def test_execute_reports_gmail_failure(wired) -> None:
    wired["gmail"] = _FakeGmail(fail=RuntimeError("quota exceeded"))
    result = _run()
    assert result.startswith("Error: the email could not be sent")
    assert "quota exceeded" in result
