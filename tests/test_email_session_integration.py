from __future__ import annotations

import logging

import pytest

# Import the app first: importing emit-dependent modules in isolation hits a
# pre-existing emit <-> session_store circular import.
from src.ui_connector.app import app  # noqa: I001, F401

import src.ui_connector.socket_handler_components.automation_approval as approval
from src.ui_connector.heartbeat_daemon import HeartbeatSession
from src.ui_connector.heartbeat_runner import HeartbeatRunner
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components.turn_outcome import (
    NO_FINAL_ANSWER_ERROR,
    TurnOutcome,
    outcome_from_turn,
)
from src.utils.sql.agents_db import Agent
from src.utils.session_model import (
    SUBTURN_ORIGIN_EMAIL,
    SUBTURN_ORIGIN_HEARTBEAT,
    SUBTURN_ORIGIN_USER,
    LLMExchange,
    Session,
    Subturn,
    Turn,
)


def _agent(**overrides) -> Agent:
    values = dict(
        id="agent-1",
        slug="helper",
        name="Helper",
        email="agent@example.test",
        registered_at=1.0,
        enabled=True,
        allowed_senders=("person@example.test",),
        profile_name="agent-profile",
        approval_mode="full-auto",
        automation_approval_policy="force-fail",
        created_at=1.0,
    )
    values.update(overrides)
    return Agent(**values)


# -- approval policy by origin ----------------------------------------------


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (SUBTURN_ORIGIN_EMAIL, False),
        (SUBTURN_ORIGIN_HEARTBEAT, None),  # heartbeat policy is wait-for-human
        (SUBTURN_ORIGIN_USER, None),
    ],
)
def test_agent_policy_applies_only_to_email_subturns(
    monkeypatch, origin, expected
) -> None:
    monkeypatch.setattr(approval, "_emit_backend_log", lambda *_a: None)
    monkeypatch.setattr(approval, "get_agent", lambda _id: _agent())
    monkeypatch.setattr(runtime_settings, "get_agent", lambda _id: _agent())
    session_id = f"email-approval-{origin}"
    session = Session(session_id=session_id, agent_id="agent-1")
    turn = Turn(id="t1", subturns=[Subturn("st1", "hi", "hi", origin=origin)])
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


def test_outcome_does_not_treat_a_failure_marker_as_the_answer() -> None:
    marker = LLMExchange(
        assistant_content="[Request Failed - Network Error]", is_final=True
    )
    turn, subturn = _turn_with([marker])
    subturn.failure_message = "Request failed: could not connect."
    assert outcome_from_turn(turn, subturn) == TurnOutcome.failed(
        "Request failed: could not connect."
    )
