from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components._session_event_emit import (
    compute_events,
)
from src.utils import session_events
from src.utils.session_model import Session


def test_runtime_settings_are_revisioned_and_merge_into_stale_session() -> None:
    session_id = "runtime-settings-test"
    original = Session(
        session_id=session_id,
        profile_name="profile-a",
        approval_mode="default",
    )
    stale_loop_copy = Session(
        session_id=session_id,
        profile_name="profile-a",
        approval_mode="default",
    )
    try:
        profile = runtime_settings.set_profile(session_id, original, "profile-b")
        approval = runtime_settings.set_approval_mode(session_id, original, "full-auto")

        assert profile.profile_revision == 1
        assert approval.approval_mode_revision == 1

        runtime_settings.merge_into_session(session_id, stale_loop_copy)
        assert stale_loop_copy.profile_name == "profile-b"
        assert stale_loop_copy.approval_mode == "full-auto"
    finally:
        runtime_settings.discard(session_id)


def test_profile_change_is_emitted_and_replayed() -> None:
    session = Session(session_id="s1", profile_name="profile-a")
    cursor: dict = {}
    initial = compute_events(session, cursor)
    session.profile_name = "profile-b"

    changed = compute_events(session, cursor)

    assert changed == [(session_events.EVT_PROFILE_SET, {"profile_name": "profile-b"})]
    rows = [
        {"event_type": event_type, "payload": payload}
        for event_type, payload in initial + changed
    ]
    restored = session_events.replay_events("s1", rows)
    assert restored.profile_name == "profile-b"


def test_heartbeat_settings_are_revisioned_and_merge_into_stale_session() -> None:
    session_id = "heartbeat-runtime-settings-test"
    original = Session(session_id=session_id)
    stale_loop_copy = Session(session_id=session_id)
    new_settings = {
        "enabled": True,
        "interval_minutes": 15,
        "instructions": "check for CI failures",
        "heartbeat_approval_policy": "force-fail",
        "followup_behavior": "new-task",
    }
    try:
        heartbeat = runtime_settings.set_heartbeat_settings(
            session_id, original, new_settings
        )

        assert heartbeat.heartbeat_settings_revision == 1
        assert heartbeat.heartbeat_settings == new_settings

        runtime_settings.merge_into_session(session_id, stale_loop_copy)
        assert stale_loop_copy.session_data["heartbeat_settings"] == new_settings
    finally:
        runtime_settings.discard(session_id)


def test_heartbeat_settings_change_is_emitted_and_replayed() -> None:
    session = Session(session_id="s1")
    cursor: dict = {}
    initial = compute_events(session, cursor)
    new_settings = {
        "enabled": True,
        "interval_minutes": 45,
        "instructions": "ping every 45 minutes",
        "heartbeat_approval_policy": "wait-for-human",
        "followup_behavior": "follow-up",
    }
    session.session_data["heartbeat_settings"] = new_settings

    changed = compute_events(session, cursor)

    assert changed == [
        (session_events.EVT_HEARTBEAT_SETTINGS_SET, {"settings": new_settings})
    ]
    rows = [
        {"event_type": event_type, "payload": payload}
        for event_type, payload in initial + changed
    ]
    restored = session_events.replay_events("s1", rows)
    assert restored.session_data["heartbeat_settings"] == new_settings


def test_settings_saved_before_followup_behavior_replay_with_auto() -> None:
    from src.utils.session_events import replay_events

    old = {
        "enabled": True,
        "interval_minutes": 30,
        "instructions": "check",
        "heartbeat_approval_policy": "wait-for-human",
    }
    rows = [
        {"event_type": "session_created", "payload": {}},
        {"event_type": "heartbeat_settings_set", "payload": {"settings": old}},
    ]
    restored = replay_events("s1", rows)
    assert restored.session_data["heartbeat_settings"] == {
        **old,
        "followup_behavior": "auto",
    }


def test_followup_behavior_is_validated() -> None:
    from src.utils.heartbeat_settings import (
        DEFAULT_HEARTBEAT_SETTINGS,
        is_valid_heartbeat_settings,
    )

    for behavior in ("auto", "follow-up", "new-task"):
        ok, _ = is_valid_heartbeat_settings(
            {**DEFAULT_HEARTBEAT_SETTINGS, "followup_behavior": behavior}
        )
        assert ok
    ok, error = is_valid_heartbeat_settings(
        {**DEFAULT_HEARTBEAT_SETTINGS, "followup_behavior": "sometimes"}
    )
    assert not ok and "followup_behavior" in error
