from __future__ import annotations

import os

import src.ui_connector.socket_handler_components.state as _state
from src.logic.system_prompt import (
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)
from src.tools import ALL_TOOL_DEFINITIONS, _TOOL_MAP, reload_custom_tools
from src.ui_connector.socket_handler_components.state import SessionToolManifest
from src.ui_connector.socket_handler_components.terminal import (
    _build_starting_environment_info,
)
from src.utils.session_model import Session


def manifest_from_custom_tools(result) -> SessionToolManifest:
    excluded = {
        name for name, flags in result.custom_exclusions.items() if flags.get("loading")
    }
    base_defs = [
        definition
        for definition in ALL_TOOL_DEFINITIONS
        if definition.get("function", {}).get("name") not in excluded
    ] + result.unscoped_defs
    base_map = {name: tool for name, tool in _TOOL_MAP.items() if name not in excluded}
    base_map.update(result.unscoped_map)
    return SessionToolManifest(
        base_defs=base_defs,
        base_map=base_map,
        by_skill=result.by_skill,
        plugins=result.plugins,
    )


def reload_session_customizations(session: Session, session_id: str) -> None:
    """Validate and atomically publish refreshed skills, tools, and prompt."""
    if not session.load_custom_skills_tools:
        raise RuntimeError("Custom skills and tools are disabled for this session.")

    registry = build_skill_registry(
        custom_skills_path=os.path.join(session.initial_cwd, "skills")
    )
    result = reload_custom_tools(
        tools_dir=os.path.join(session.initial_cwd, "tools"),
        workspace_root=session.initial_cwd or None,
        session_prefix=session_id[:8],
        known_skill_ids=frozenset(entry["id"] for entry in registry),
    )
    manifest = manifest_from_custom_tools(result)
    system_prompt = build_system_prompt(
        starting_environment_info=_build_starting_environment_info(session),
        autoload_entries=get_autoload_skill_entries(registry),
    )

    if session_id in _state._session_active_turns:
        raise RuntimeError(
            "Cannot reload custom skills and tools during an active turn."
        )

    _state._session_skill_registries[session_id] = registry
    _state._session_tool_sets[session_id] = manifest
    _state._session_system_prompts[session_id] = system_prompt
    session.session_data["__skill_files__"] = registry
