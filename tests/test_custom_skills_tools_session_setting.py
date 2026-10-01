from click.testing import CliRunner

from src.cli_obj import cli
import src.cli_routes.session  # noqa: F401 - registers the route
from src.utils.session_events import replay_events, session_created_payload
from src.utils.session_model import Session
from src.utils.session_schema_repair import repair_event_log


def test_cli_exposes_only_combined_custom_loading_flag():
    result = CliRunner().invoke(cli, ["session", "new", "--help"])

    assert result.exit_code == 0
    assert "--load-custom-skills-tools" in result.output
    assert "--load-skills" not in result.output
    assert "--load-tools" not in result.output


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
    restored = replay_events(
        "s1", [{"event_type": "session_created", "payload": payload}]
    )
    assert restored.load_custom_skills_tools is True
