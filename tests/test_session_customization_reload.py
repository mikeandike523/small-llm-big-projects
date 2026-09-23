from types import SimpleNamespace

import pytest

# Establish the socket module import order used by the application. The app and
# handler modules have a pre-existing cycle that requires app to bind first.
import src.ui_connector.app  # noqa: F401
import src.ui_connector.socket_handler_components.session_customizations as reloads
import src.ui_connector.socket_handler_components.state as state
from src.utils.session_model import Session


def _tool_result():
    return SimpleNamespace(
        custom_exclusions={},
        unscoped_defs=[],
        unscoped_map={},
        by_skill={},
        plugins=[],
    )


def test_reload_publishes_skills_tools_and_prompt_together(monkeypatch, tmp_path):
    session_id = "reload-success"
    session = Session(
        session_id=session_id,
        initial_cwd=str(tmp_path),
        load_custom_skills_tools=True,
    )
    registry = [
        {
            "id": "fresh",
            "name": "Fresh",
            "source": "custom",
            "autoload": False,
        }
    ]
    monkeypatch.setattr(reloads, "build_skill_registry", lambda **_kwargs: registry)
    monkeypatch.setattr(reloads, "reload_custom_tools", lambda **_kwargs: _tool_result())
    monkeypatch.setattr(reloads, "build_system_prompt", lambda **_kwargs: "new prompt")

    try:
        reloads.reload_session_customizations(session, session_id)

        assert state._session_skill_registries[session_id] is registry
        assert state._session_system_prompts[session_id] == "new prompt"
        assert state._session_tool_sets[session_id].by_skill == {}
        assert session.session_data["__skill_files__"] is registry
    finally:
        state._session_skill_registries.pop(session_id, None)
        state._session_system_prompts.pop(session_id, None)
        state._session_tool_sets.pop(session_id, None)


def test_reload_does_not_publish_if_turn_started_during_validation(
    monkeypatch, tmp_path
):
    session_id = "reload-race"
    session = Session(
        session_id=session_id,
        initial_cwd=str(tmp_path),
        load_custom_skills_tools=True,
    )
    old_registry = [{"id": "old"}]
    state._session_skill_registries[session_id] = old_registry
    monkeypatch.setattr(reloads, "build_skill_registry", lambda **_kwargs: [])

    def start_turn(**_kwargs):
        state._session_active_turns.add(session_id)
        return _tool_result()

    monkeypatch.setattr(reloads, "reload_custom_tools", start_turn)
    monkeypatch.setattr(reloads, "build_system_prompt", lambda **_kwargs: "new prompt")

    try:
        with pytest.raises(RuntimeError, match="active turn"):
            reloads.reload_session_customizations(session, session_id)
        assert state._session_skill_registries[session_id] is old_registry
        assert session_id not in state._session_system_prompts
    finally:
        state._session_active_turns.discard(session_id)
        state._session_skill_registries.pop(session_id, None)
