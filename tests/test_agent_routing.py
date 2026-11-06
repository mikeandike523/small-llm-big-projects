"""The conversation rules: which session answers which email."""

from __future__ import annotations

import pytest

import src.channels.email.session_spawn as spawn
from src.channels.email.inbound_store import InboundEmail
from src.channels.email.router import sender_display_name
from src.utils.sql.agents_db import Agent, AgentSender


def _row(thread="t1", sender="ana@example.test", name="Ana Diaz") -> InboundEmail:
    return InboundEmail(
        id=1,
        agent_id="a1",
        session_id=None,
        gmail_message_id="m1",
        gmail_thread_id=thread,
        alias="agent@example.test",
        sender_address=sender,
        sender_display_name=name,
        subject="Hello",
        message_id_header="<m1@mail.example.test>",
        references_header="",
        body_text="hi",
        received_at=1.0,
        sent_at=1.0,
        status="queued",
        needs_queued_reply=False,
        queued_reply_sent_at=None,
        working_reply_sent_at=None,
        final_reply_sent_at=None,
        approval_notice_sent_at=None,
        final_text=None,
        error_detail=None,
    )


AGENT = Agent(
    id="a1",
    slug="helper",
    name="Helper",
    email="agent@example.test",
    registered_at=1.0,
    enabled=True,
    allowed_senders=("ana@example.test", "bob@example.test"),
    profile_name="agent-profile",
    approval_mode="full-auto",
    automation_approval_policy="force-approve",
    created_at=1.0,
)


@pytest.fixture
def db(monkeypatch):
    state = {
        "senders": {},
        "conversations": {},
        "saved": [],
        "user_dirs": [],
        "names": [],
    }
    m = monkeypatch.setattr
    m(spawn, "get_agent", lambda _id: AGENT)
    m(
        spawn.agents_db,
        "load_sender",
        lambda _aid, address: state["senders"].get(address),
    )
    m(
        spawn.agents_db,
        "list_sender_slugs",
        lambda _aid: {s.slug for s in state["senders"].values()},
    )
    m(
        spawn.agents_db,
        "insert_sender",
        lambda sender: state["senders"].update({sender.sender_address: sender}),
    )
    m(
        spawn.agents_db,
        "update_sender_display_name",
        lambda _aid, address, name: state["names"].append((address, name)),
    )
    m(
        spawn.agents_db,
        "conversation_session",
        lambda aid, thread, sender: state["conversations"].get((aid, thread, sender)),
    )
    m(
        spawn.agents_db,
        "insert_conversation",
        lambda aid, thread, sender, sid: state["conversations"].update(
            {(aid, thread, sender): sid}
        ),
    )
    m(spawn, "ensure_session_dirs", lambda *_a: None)

    def ensure_user_dir(agent_slug, user_slug):
        path = f"/agents/{agent_slug}/workspace/users/{user_slug}"
        state["user_dirs"].append(path)
        return path

    m(spawn, "ensure_user_dir", ensure_user_dir)
    m(
        spawn,
        "persist_save",
        lambda sid, events, _t, _s, meta: state["saved"].append((sid, events, meta)),
    )
    return state


def test_first_email_spawns_a_locked_down_session(db) -> None:
    session_id = spawn.session_for_email(_row())
    saved_id, events, meta = db["saved"][0]
    assert saved_id == session_id
    payload = events[0][1]
    assert events[0][0] == "session_created"
    assert payload["agent_id"] == "a1"
    assert payload["initial_cwd"] == "/agents/helper/workspace/users/ana-diaz"
    assert payload["load_custom_skills_tools"] is False
    assert payload["startup_done"] is True
    assert payload["profile_name"] == "agent-profile"
    assert meta["agent_id"] == "a1"


def test_reply_from_the_same_sender_reuses_the_session(db) -> None:
    first = spawn.session_for_email(_row())
    assert spawn.session_for_email(_row()) == first
    assert len(db["saved"]) == 1


def test_new_thread_from_the_same_sender_gets_a_new_session(db) -> None:
    first = spawn.session_for_email(_row(thread="t1"))
    second = spawn.session_for_email(_row(thread="t2"))
    assert second != first
    assert db["user_dirs"] == [
        "/agents/helper/workspace/users/ana-diaz",
        "/agents/helper/workspace/users/ana-diaz",
    ]


def test_new_sender_in_an_existing_thread_gets_a_new_session(db) -> None:
    first = spawn.session_for_email(_row(sender="ana@example.test"))
    second = spawn.session_for_email(_row(sender="bob@example.test", name="Bob"))
    assert second != first
    assert db["user_dirs"][-1] == "/agents/helper/workspace/users/bob"


def test_deleted_session_means_the_next_reply_starts_a_new_one(db) -> None:
    first = spawn.session_for_email(_row())
    db["conversations"].clear()  # ON DELETE CASCADE from session_meta
    assert spawn.session_for_email(_row()) != first


def test_same_name_from_two_addresses_gets_separate_folders(db) -> None:
    spawn.session_for_email(_row(sender="ana@example.test", name="Ana"))
    spawn.session_for_email(_row(sender="ana2@example.test", name="Ana"))
    assert db["user_dirs"] == [
        "/agents/helper/workspace/users/ana",
        "/agents/helper/workspace/users/ana-2",
    ]


def test_folder_never_follows_a_changed_display_name(db) -> None:
    spawn.session_for_email(_row(thread="t1", name="Ana"))
    spawn.session_for_email(_row(thread="t2", name="Someone Else"))
    assert db["user_dirs"] == [
        "/agents/helper/workspace/users/ana",
        "/agents/helper/workspace/users/ana",
    ]
    assert db["names"] == [("ana@example.test", "Someone Else")]


def test_ensure_folder_recreates_it(db) -> None:
    db["senders"]["ana@example.test"] = AgentSender(
        "a1", "ana@example.test", "ana-diaz", "Ana Diaz"
    )
    assert spawn.ensure_user_folder(_row()) is None
    assert db["user_dirs"] == ["/agents/helper/workspace/users/ana-diaz"]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Ana Diaz <ana@example.test>", "Ana Diaz"),
        ('"Diaz, Ana"   <ana@example.test>', "Diaz, Ana"),
        ("ana@example.test", None),
        ("", None),
    ],
)
def test_display_name_comes_from_the_from_header(header, expected) -> None:
    assert sender_display_name(header) == expected
