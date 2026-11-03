from __future__ import annotations

import logging

import pytest

# Import the app first: importing emit-dependent modules in isolation hits a
# pre-existing emit <-> session_store circular import.
from src.ui_connector.app import app  # noqa: I001

import src.channels.email.email_runner as email_runner
import src.ui_connector.socket_handler_components.automation_approval as approval
import src.ui_connector.socket_handler_components.email_settings_api as api
from src.ui_connector.heartbeat_daemon import HeartbeatSession
from src.ui_connector.heartbeat_runner import HeartbeatRunner
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.llm import _build_llm_payload
from src.ui_connector.socket_handler_components.turn_outcome import (
    NO_FINAL_ANSWER_ERROR,
    TurnOutcome,
    outcome_from_turn,
)
from src.utils.email_settings import (
    DEFAULT_EMAIL_SETTINGS,
    EMAIL_MULTITASK_PROMPT_NOTE,
)
from src.utils.session_model import (
    SUBTURN_ORIGIN_EMAIL,
    SUBTURN_ORIGIN_HEARTBEAT,
    SUBTURN_ORIGIN_USER,
    LLMExchange,
    Session,
    Subturn,
    Turn,
)


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


@pytest.fixture
def route_env(monkeypatch):
    session_id = "email-route-s1"
    state = {"persisted": [], "owner": None, "persist_error": None, "discarded": []}
    monkeypatch.setattr(api, "_load_session_info", lambda sid: Session(session_id=sid))
    monkeypatch.setattr(api, "find_alias_owner", lambda *_a, **_k: state["owner"])

    def persist(sid, settings):
        if state["persist_error"] is not None:
            raise state["persist_error"]
        state["persisted"].append(settings)

    monkeypatch.setattr(api, "persist_email_settings", persist)
    monkeypatch.setattr(api.socketio, "emit", lambda *a, **k: None)
    monkeypatch.setattr(
        email_runner,
        "discard_queued_email",
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


# -- approval policy by origin ----------------------------------------------


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
    session_id = f"email-approval-{origin}"
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


# -- heartbeat never cancels an email turn ----------------------------------


def test_heartbeat_skips_email_owned_turn_without_cancel(caplog) -> None:
    cancels: list[str] = []
    runner = HeartbeatRunner(
        launch=lambda *_a: False,
        running_turn_owner=lambda _sid: SUBTURN_ORIGIN_EMAIL,
        cancel=cancels.append,
        retry_seconds=0,
    )
    with caplog.at_level(logging.INFO):
        assert runner(HeartbeatSession("s1", 5, "do work", "auto")) is False
    assert cancels == []
    assert "has a running email turn" in caplog.text


# -- turn outcome mapping ----------------------------------------------------


def _turn_with(
    exchanges: list[LLMExchange], *, cancelled=False
) -> tuple[Turn, Subturn]:
    subturn = Subturn("st1", "hi", "hi", exchanges=exchanges)
    return Turn(id="t1", subturns=[subturn], was_cancelled=cancelled), subturn


def test_outcome_maps_answer_cancel_and_missing_answer() -> None:
    final = LLMExchange(assistant_content="Done!", is_final=True)
    assert outcome_from_turn(*_turn_with([final])) == TurnOutcome(final_text="Done!")
    assert outcome_from_turn(*_turn_with([final], cancelled=True)).cancelled
    missing = outcome_from_turn(*_turn_with([]))
    assert missing.final_text is None and missing.error == NO_FINAL_ANSWER_ERROR


# -- system prompt note ------------------------------------------------------


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
