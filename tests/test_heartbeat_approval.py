from __future__ import annotations

import pytest

import src.ui_connector.socket_handler_components.heartbeat_approval as hb_approval
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components._session_event_emit import (
    compute_events,
)
from src.utils import session_events
from src.utils.heartbeat_settings import DEFAULT_HEARTBEAT_SETTINGS
from src.utils.session_model import (
    SUBTURN_ORIGIN_HEARTBEAT,
    SUBTURN_ORIGIN_USER,
    Session,
    Subturn,
    Turn,
)


def _session(session_id: str, policy: str, origin: str) -> tuple[Session, Turn]:
    session = Session(session_id=session_id)
    turn = Turn(id="t1", subturns=[Subturn("st1", "hi", "hi", origin=origin)])
    runtime_settings.set_heartbeat_settings(
        session_id,
        session,
        {**DEFAULT_HEARTBEAT_SETTINGS, "heartbeat_approval_policy": policy},
    )
    return session, turn


@pytest.fixture(autouse=True)
def _quiet_backend_log(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(
        hb_approval, "_emit_backend_log", lambda _sid, msg: logs.append(msg)
    )
    return logs


@pytest.mark.parametrize(
    ("policy", "origin", "expected"),
    [
        ("wait-for-human", SUBTURN_ORIGIN_HEARTBEAT, None),
        ("force-fail", SUBTURN_ORIGIN_HEARTBEAT, False),
        ("force-approve", SUBTURN_ORIGIN_HEARTBEAT, True),
        ("force-fail", SUBTURN_ORIGIN_USER, None),
        ("force-approve", SUBTURN_ORIGIN_USER, None),
    ],
)
def test_policy_applies_only_to_heartbeat_subturns(policy, origin, expected) -> None:
    session_id = f"hb-approval-{policy}-{origin}"
    session, turn = _session(session_id, policy, origin)
    try:
        assert (
            hb_approval.heartbeat_approval_override(
                session_id, session, turn, "st1", "host_shell"
            )
            is expected
        )
    finally:
        runtime_settings.discard(session_id)


def test_user_followup_in_heartbeat_turn_waits_for_human() -> None:
    session_id = "hb-approval-followup"
    session, turn = _session(session_id, "force-fail", SUBTURN_ORIGIN_HEARTBEAT)
    turn.subturns.append(Subturn("st2", "more", "more", is_continuation=True))
    try:
        assert (
            hb_approval.heartbeat_approval_override(
                session_id, session, turn, "st2", "host_shell"
            )
            is None
        )
    finally:
        runtime_settings.discard(session_id)


def test_forced_decision_is_logged_to_debug_panel(_quiet_backend_log) -> None:
    session_id = "hb-approval-log"
    session, turn = _session(session_id, "force-fail", SUBTURN_ORIGIN_HEARTBEAT)
    try:
        hb_approval.heartbeat_approval_override(
            session_id, session, turn, "st1", "read_text_file"
        )
    finally:
        runtime_settings.discard(session_id)
    assert _quiet_backend_log == [
        "Heartbeat approval policy force-fail: auto-denied read_text_file "
        f"(session_id={session_id} turn_id=t1)"
    ]


def test_subturn_origin_defaults_to_user_for_legacy_events() -> None:
    session = Session(session_id="s1")
    session.current_turn = Turn(
        id="t1", subturns=[Subturn("st1", "hi", "hi", origin=SUBTURN_ORIGIN_HEARTBEAT)]
    )
    rows = [
        {"event_type": event_type, "payload": dict(payload)}
        for event_type, payload in compute_events(session, {})
    ]
    for row in rows:
        if row["event_type"] == "subturn_started":
            del row["payload"]["origin"]
    restored = session_events.replay_events("s1", rows)
    assert restored.current_turn.subturns[0].origin == SUBTURN_ORIGIN_USER


def test_subturn_origin_survives_event_replay() -> None:
    session = Session(session_id="s1")
    session.current_turn = Turn(
        id="t1", subturns=[Subturn("st1", "hi", "hi", origin=SUBTURN_ORIGIN_HEARTBEAT)]
    )
    rows = [
        {"event_type": event_type, "payload": payload}
        for event_type, payload in compute_events(session, {})
    ]
    restored = session_events.replay_events("s1", rows)
    assert restored.current_turn.subturns[0].origin == SUBTURN_ORIGIN_HEARTBEAT
