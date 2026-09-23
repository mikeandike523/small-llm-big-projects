from click.testing import CliRunner

from src.cli_obj import cli
import src.cli_routes.session  # noqa: F401 - registers the route
from src.utils.session_events import replay_events, session_created_payload
from src.utils.session_model import Session, session_from_dict, session_to_dict
from src.utils.session_schema_repair import repair_event_log, repair_session_dict


def test_cli_exposes_only_combined_custom_loading_flag():
    result = CliRunner().invoke(cli, ["session", "new", "--help"])

    assert result.exit_code == 0
    assert "--load-custom-skills-tools" in result.output
    assert "--load-skills" not in result.output
    assert "--load-tools" not in result.output


def test_session_round_trip_uses_combined_setting():
    original = Session(
        session_id="s1",
        initial_cwd="/workspace",
        load_custom_skills_tools=True,
    )

    serialized = session_to_dict(original)
    restored = session_from_dict(serialized)

    assert serialized["load_custom_skills_tools"] is True
    assert "skills_path" not in serialized
    assert "custom_tools_path" not in serialized
    assert restored.load_custom_skills_tools is True


def test_v5_redis_repair_requires_both_legacy_paths():
    enabled = repair_session_dict(
        {
            "schema_version": 5,
            "session_id": "enabled",
            "skills_path": "/workspace/skills",
            "custom_tools_path": "/workspace/tools",
        },
        6,
    )
    disabled = repair_session_dict(
        {
            "schema_version": 5,
            "session_id": "disabled",
            "skills_path": "/workspace/skills",
            "custom_tools_path": None,
        },
        6,
    )

    assert enabled["load_custom_skills_tools"] is True
    assert disabled["load_custom_skills_tools"] is False
    for repaired in (enabled, disabled):
        assert repaired["schema_version"] == 6
        assert "skills_path" not in repaired
        assert "custom_tools_path" not in repaired


def test_v5_event_repair_requires_both_legacy_paths():
    meta, rows = repair_event_log(
        {
            "schema_version": 5,
            "skills_path": "/workspace/skills",
            "custom_tools_path": None,
        },
        [
            {
                "event_type": "session_created",
                "payload": {
                    "schema_version": 5,
                    "initial_cwd": "/workspace",
                    "skills_path": "/workspace/skills",
                    "custom_tools_path": None,
                },
            }
        ],
        6,
    )

    assert meta["load_custom_skills_tools"] is False
    assert rows[0]["payload"]["load_custom_skills_tools"] is False
    restored = replay_events("s1", rows)
    assert restored.load_custom_skills_tools is False


def test_new_session_created_event_uses_combined_setting():
    payload = session_created_payload(
        Session(session_id="s1", load_custom_skills_tools=True)
    )

    assert payload["load_custom_skills_tools"] is True
    assert "skills_path" not in payload
    assert "custom_tools_path" not in payload
