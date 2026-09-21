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
