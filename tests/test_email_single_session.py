"""One session answering one alias, alongside agent pools."""

from __future__ import annotations

import pytest

# Import the app first: importing emit-dependent modules in isolation hits a
# pre-existing emit <-> session_store circular import.
from src.ui_connector.app import app  # noqa: I001

import src.channels.email.email_runner as email_runner
import src.channels.email.router as router
import src.ui_connector.socket_handler_components.automation_approval as approval
import src.ui_connector.socket_handler_components.email_settings_api as api
import src.utils.agent_store as agent_store
import src.utils.email_claims as email_claims
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.llm import _build_llm_payload
from src.utils.agent_settings import AgentIdentity, AgentSettings
from src.utils.agent_store import AgentConflictError
from src.utils.email_settings import (
    DEFAULT_EMAIL_SETTINGS,
    EMAIL_MULTITASK_PROMPT_NOTE,
)
from src.utils.session_events import EVT_EMAIL_SETTINGS_SET, ReplayState
from src.utils.session_model import (
    SUBTURN_ORIGIN_EMAIL,
    SUBTURN_ORIGIN_HEARTBEAT,
    SUBTURN_ORIGIN_USER,
    Session,
    Subturn,
    Turn,
)
from src.utils.sql import agents_db
from src.utils.sql.email_alias_db import AliasClaim
from test_email_router import _message
from test_email_runner import Harness


class DuplicateKey(Exception):
    errno = 1062


def _body(**overrides) -> dict:
    return {
        "enabled": True,
        "alias": "Agent@Example.test",
        "agent_name": "Helper",
        "allowed_senders": "person@example.test",
        "email_approval_policy": "force-fail",
        "followup_behavior": "auto",
        **overrides,
    }


# -- the settings route ------------------------------------------------------


@pytest.fixture
def route_env(monkeypatch):
    session_id = "email-route-s1"
    state = {
        "persisted": [],
        "owner": None,
        "agent_holder": None,
        "persist_error": None,
        "discarded": [],
        "agent_id": None,
    }
    monkeypatch.setattr(
        api,
        "_load_session_info",
        lambda sid: Session(session_id=sid, agent_id=state["agent_id"]),
    )
    monkeypatch.setattr(api, "find_alias_owner", lambda *_a, **_k: state["owner"])
    monkeypatch.setattr(
        api, "held_by_agent_message", lambda _alias: state["agent_holder"]
    )

    def persist(sid, settings):
        if state["persist_error"] is not None:
            raise state["persist_error"]
        state["persisted"].append(settings)

    monkeypatch.setattr(api, "persist_email_settings", persist)
    monkeypatch.setattr(api.socketio, "emit", lambda *a, **k: None)
    monkeypatch.setattr(
        api,
        "discard_queued_for_session",
        lambda sid: state["discarded"].append(sid) or 0,
    )
    monkeypatch.setattr(email_runner, "notify_email_runner", lambda: None)
    yield session_id, state, app.test_client()
    runtime_settings.discard(session_id)


def _patch(client, session_id, body):
    return client.patch(f"/api/sessions/{session_id}/email-settings", json=body)


def test_claim_sets_server_claim_time_and_normalizes(route_env) -> None:
    session_id, state, client = route_env
    response = _patch(client, session_id, _body(alias_claimed_at=1.0))
    assert response.status_code == 200
    saved = state["persisted"][0]
    assert saved["alias"] == "agent@example.test"
    assert saved["allowed_senders"] == ["person@example.test"]
    assert saved["alias_claimed_at"] > 1.0
    assert response.get_json()["emailSettings"]["alias"] == "agent@example.test"
    assert state["discarded"] == [session_id]  # alias changed


def test_unchanged_alias_keeps_its_claim_time(route_env) -> None:
    session_id, state, client = route_env
    _patch(client, session_id, _body())
    first = state["persisted"][0]["alias_claimed_at"]
    _patch(client, session_id, _body(agent_name="Renamed"))
    assert state["persisted"][1]["alias_claimed_at"] == first
    assert state["discarded"] == [session_id]  # only the first save discarded


def test_alias_owned_by_another_session_is_409(route_env) -> None:
    session_id, state, client = route_env
    state["owner"] = {"session_id": "other", "title": "Other task"}
    response = _patch(client, session_id, _body())
    assert response.status_code == 409
    data = response.get_json()
    assert data["field"] == "alias"
    assert data["owner_session_id"] == "other"
    assert "Other task" in data["error"]
    assert state["persisted"] == []


def test_alias_held_by_an_agent_is_409(route_env) -> None:
    session_id, state, client = route_env
    state["agent_holder"] = "agent@example.test is already used by agent Helper."
    response = _patch(client, session_id, _body())
    assert response.status_code == 409
    assert response.get_json() == {
        "error": state["agent_holder"],
        "field": "alias",
    }
    assert state["persisted"] == []


def test_unique_index_race_is_also_409(route_env) -> None:
    session_id, state, client = route_env
    state["persist_error"] = DuplicateKey("duplicate entry")
    response = _patch(client, session_id, _body())
    assert response.status_code == 409
    assert response.get_json()["field"] == "alias"


def test_invalid_sender_line_is_400_with_field(route_env) -> None:
    session_id, _state, client = route_env
    response = _patch(client, session_id, _body(allowed_senders="ok@example.test\nbad"))
    assert response.status_code == 400
    assert response.get_json()["field"] == "allowed_senders"


def test_disabling_discards_queue_but_keeps_alias(route_env) -> None:
    session_id, state, client = route_env
    _patch(client, session_id, _body())
    _patch(client, session_id, _body(enabled=False))
    assert state["persisted"][1]["alias"] == "agent@example.test"
    assert state["discarded"] == [session_id, session_id]


def test_pool_session_cannot_have_its_own_email_settings(route_env) -> None:
    session_id, state, client = route_env
    state["agent_id"] = "agent-1"
    response = _patch(client, session_id, _body())
    assert response.status_code == 409
    assert state["persisted"] == []


# -- one owner per address ---------------------------------------------------


SETTINGS = AgentSettings(
    enabled=True,
    allowed_senders=["person@example.test"],
    profile_name="p",
    approval_mode="default",
    automation_approval_policy="wait-for-human",
)


def _agent_db_no_conflict(monkeypatch) -> list:
    inserted: list = []
    monkeypatch.setattr(agents_db, "identity_conflict", lambda *_a, **_k: None)
    monkeypatch.setattr(agents_db, "insert_agent", lambda *a, **k: inserted.append(a))
    monkeypatch.setattr(agent_store, "ensure_agent_dirs", lambda _slug: None)
    return inserted


def test_agent_cannot_take_an_address_a_session_holds(monkeypatch) -> None:
    inserted = _agent_db_no_conflict(monkeypatch)
    monkeypatch.setattr(
        email_claims,
        "find_alias_owner",
        lambda *_a, **_k: {"session_id": "s1", "title": "Weekly report"},
    )
    with pytest.raises(AgentConflictError, match='session "Weekly report"') as info:
        agent_store.create_agent(AgentIdentity("Ana", "a@example.test"), SETTINGS)
    assert info.value.field == "email"
    assert inserted == []


def test_agent_can_take_a_free_address(monkeypatch) -> None:
    inserted = _agent_db_no_conflict(monkeypatch)
    monkeypatch.setattr(email_claims, "find_alias_owner", lambda *_a, **_k: None)
    agent_store.create_agent(AgentIdentity("Ana", "a@example.test"), SETTINGS)
    assert len(inserted) == 1


def test_unretiring_also_checks_sessions(monkeypatch) -> None:
    _agent_db_no_conflict(monkeypatch)
    retired = agents_db.Agent(
        id="a1",
        slug="ana",
        name="Ana",
        email="a@example.test",
        registered_at=1.0,
        enabled=True,
        allowed_senders=(),
        profile_name="p",
        approval_mode="default",
        automation_approval_policy="wait-for-human",
        created_at=1.0,
        retired_at=2.0,
    )
    reactivated: list = []
    monkeypatch.setattr(agents_db, "load_agent", lambda _aid: retired)
    monkeypatch.setattr(
        agents_db, "set_retired", lambda *a, **k: reactivated.append((a, k))
    )
    monkeypatch.setattr(
        email_claims,
        "find_alias_owner",
        lambda *_a, **_k: {"session_id": "s1", "title": None},
    )
    with pytest.raises(AgentConflictError, match="a session"):
        agent_store.unretire("a1")
    assert reactivated == []


# -- routing -----------------------------------------------------------------


class RouteEnv:
    def __init__(self, monkeypatch, *, enabled=True, claimed_at=1000.0, senders=None):
        self.inserted: list = []
        monkeypatch.setattr(router, "load_agents_for_emails", lambda _emails: [])
        monkeypatch.setattr(
            router,
            "list_alias_claims",
            lambda emails: [
                AliasClaim("s1", alias, enabled, claimed_at, 1.0)
                for alias in emails
                if alias == "agent@example.test"
            ],
        )
        monkeypatch.setattr(
            router,
            "email_settings_for",
            lambda _sid: {
                "allowed_senders": (
                    ["person@example.test"] if senders is None else senders
                )
            },
        )
        monkeypatch.setattr(router, "_session_is_busy", lambda _sid: True)
        self.quote_lookups: list = []
        monkeypatch.setattr(
            router,
            "sent_final_texts_for_session",
            lambda *a: self.quote_lookups.append(a) or [],
        )
        monkeypatch.setattr(router, "insert_inbound", self._insert)

    def _insert(self, item, *, needs_queued_reply):
        self.inserted.append((item, needs_queued_reply))
        return True


def test_alias_mail_is_queued_directly_on_its_session(monkeypatch) -> None:
    env = RouteEnv(monkeypatch)
    assert router.route_inbound_message(_message()) == ["s1"]
    item, needs_queued_reply = env.inserted[0]
    assert item.session_id == "s1"
    assert item.agent_id is None
    assert item.alias == "agent@example.test"
    assert needs_queued_reply is True
    assert env.quote_lookups == [("s1", "t1")]


def test_disabled_alias_is_dropped(monkeypatch) -> None:
    env = RouteEnv(monkeypatch, enabled=False)
    assert router.route_inbound_message(_message()) == []
    assert env.inserted == []


def test_mail_from_before_the_claim_is_dropped(monkeypatch) -> None:
    env = RouteEnv(monkeypatch, claimed_at=5000.0)
    assert router.route_inbound_message(_message()) == []
    assert env.inserted == []


def test_sender_outside_the_session_allowlist_is_dropped(monkeypatch, caplog) -> None:
    env = RouteEnv(monkeypatch, senders=["someone-else@example.test"])
    assert router.route_inbound_message(_message()) == []
    assert env.inserted == []
    assert "session_id=s1" in caplog.text


def test_sent_date_reaches_the_queue_row(monkeypatch) -> None:
    env = RouteEnv(monkeypatch)
    message = _message(
        internal_date_ms=1_800_000_000_000,  # 2027-01-15 08:00:00 UTC
        date_header="Fri, 15 Jan 2027 07:59:00 +0000",
    )
    router.route_inbound_message(message)
    item = env.inserted[0][0]
    assert item.received_at == 1_800_000_000.0
    assert item.sent_at == 1_800_000_000.0 - 60


# -- the runner --------------------------------------------------------------


def _single_session(monkeypatch) -> Harness:
    h = Harness(monkeypatch)
    h.agent = None
    return h


def test_single_session_turn_uses_its_own_settings(monkeypatch) -> None:
    h = _single_session(monkeypatch)
    row = h.store.add(agent_id=None)
    h.runner.run_pass()
    session_id, _text, title = h.launches[0]
    assert session_id == "s1"
    assert title is None  # the LLM names the turn
    assert h.followups == ["new-task"]
    assert h.folders == []
    assert h.sent == [(row.id, "[Solo is working...]")]


def test_pool_turn_keeps_its_fixed_title_and_always_follows_up(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add()
    h.runner.run_pass()
    assert h.launches[0][2] == "Message from person@example.test, id=t1"
    assert h.followups == ["follow-up"]
    assert h.folders == [row.id]


def test_unnamed_single_session_uses_the_generic_label(monkeypatch) -> None:
    h = _single_session(monkeypatch)
    h.settings["agent_name"] = "  "
    row = h.store.add(agent_id=None)
    h.runner.run_pass()
    assert h.sent == [(row.id, "[The agent is working...]")]


# -- approval policy and the prompt note -------------------------------------


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (SUBTURN_ORIGIN_EMAIL, False),
        (SUBTURN_ORIGIN_HEARTBEAT, None),  # heartbeat policy is wait-for-human
        (SUBTURN_ORIGIN_USER, None),
    ],
)
def test_email_policy_applies_only_to_email_subturns(
    monkeypatch, origin, expected
) -> None:
    monkeypatch.setattr(approval, "_emit_backend_log", lambda *_a: None)
    session_id = f"email-approval-solo-{origin}"
    session = Session(session_id=session_id)
    turn = Turn(id="t1", subturns=[Subturn("st1", "hi", "hi", origin=origin)])
    runtime_settings.set_email_settings(
        session_id,
        session,
        {**DEFAULT_EMAIL_SETTINGS, "email_approval_policy": "force-fail"},
    )
    try:
        assert (
            approval.automation_approval_override(
                session_id, session, turn, "st1", "host_shell"
            )
            is expected
        )
    finally:
        runtime_settings.discard(session_id)


def test_prompt_note_follows_the_live_enabled_flag() -> None:
    session_id = "email-prompt-note"
    session = Session(session_id=session_id)
    turn = Turn(id="t1", subturns=[Subturn("st1", "hi", "hi")])
    try:
        runtime_settings.set_email_settings(
            session_id, session, {**DEFAULT_EMAIL_SETTINGS, "enabled": True}
        )
        assert (
            EMAIL_MULTITASK_PROMPT_NOTE
            in _build_llm_payload(session, turn)[0]["content"]
        )
        runtime_settings.set_email_settings(
            session_id, session, {**DEFAULT_EMAIL_SETTINGS, "enabled": False}
        )
        assert (
            EMAIL_MULTITASK_PROMPT_NOTE
            not in _build_llm_payload(session, turn)[0]["content"]
        )
    finally:
        runtime_settings.discard(session_id)


# -- replay ------------------------------------------------------------------


def test_settings_events_from_before_v24_stay_ignored() -> None:
    state = ReplayState("s1")
    state.apply(
        "email_settings_set",
        {"settings": {"enabled": True, "alias": "old@example.test"}},
    )
    assert "email_settings" not in state.session.session_data


def test_current_settings_events_are_replayed() -> None:
    state = ReplayState("s1")
    state.apply(
        EVT_EMAIL_SETTINGS_SET,
        {"settings": {"enabled": True, "alias": "new@example.test"}},
    )
    settings = state.session.session_data["email_settings"]
    assert settings["alias"] == "new@example.test"
    assert settings["followup_behavior"] == "auto"
