from __future__ import annotations

import logging
import os

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import _emit_and_log
from src.ui_connector.socket_handler_components.terminal import (
    _build_starting_environment_info,
)
from src.ui_connector.socket_handler_components.session_setup import (
    _build_prompt_placeholders,
    _ensure_session_dirs_reported,
)
from src.ui_connector.socket_handler_components.state import SessionToolManifest
from src.tools import ALL_TOOL_DEFINITIONS, _TOOL_MAP, load_custom_tools
from src.logic.system_prompt import (
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)
from src.utils.event_log import watermark_key
from src.utils.session_dirs import delete_session_scratchpad
from src.utils.session_memory import SessionMemory
from src.utils.session_model import Session
from src.utils.sql.chat_history_cache_db import load_last_turn_rows
from src.utils.sql.session_memory_db import list_memory_keys
from src.utils.sql.session_store_db import delete_sessions
from src.ui_connector.socket_handler_components.session_db_load import (
    forget_restored_session,
    load_session_from_db,
    load_session_info_from_db,
)
from src.ui_connector.socket_handler_components.session_writes import (
    write_repaired_turn,
    write_session_created,
)
from src.ui_connector.socket_handler_components.session_customizations import (
    manifest_from_custom_tools,
)
from src.ui_connector.socket_handler_components.session_info import (
    skills_info_payload,
    tools_info_payload,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session cache accessors
# ---------------------------------------------------------------------------


def _get_session_tool_manifest(session_id: str) -> SessionToolManifest:
    manifest = _state._session_tool_sets.get(session_id)
    if manifest is None:
        return SessionToolManifest(
            base_defs=list(ALL_TOOL_DEFINITIONS), base_map=dict(_TOOL_MAP)
        )
    return manifest


def _get_session_tool_defs(session_id: str) -> list[dict]:
    """Full validated tool manifest for this session (every skill's tools, not
    just the currently-active subset). Used by the debug panel and startup
    tool calls — for the per-subturn active subset, see
    _get_active_session_tool_defs_and_map.
    """
    manifest = _get_session_tool_manifest(session_id)
    defs = list(manifest.base_defs)
    for skill_defs, _ in manifest.by_skill.values():
        defs.extend(skill_defs)
    return defs


def _get_session_tool_map(session_id: str) -> dict:
    """Full validated tool map for this session — see _get_session_tool_defs."""
    manifest = _get_session_tool_manifest(session_id)
    tool_map = dict(manifest.base_map)
    for _, skill_map in manifest.by_skill.values():
        tool_map.update(skill_map)
    return tool_map


def _get_session_plugins(session_id: str) -> list[dict]:
    return _get_session_tool_manifest(session_id).plugins


def _get_active_session_tool_defs_and_map(
    session_id: str, active_skill_ids: set[str]
) -> tuple[list[dict], dict]:
    """Tool defs/map for one subturn, narrowed to base tools + only the
    currently-active skills' tools. Recomputed fresh per subturn — see
    agent_loop.py, called right after that subturn's skill snapshot.
    """
    manifest = _get_session_tool_manifest(session_id)
    defs = list(manifest.base_defs)
    tool_map = dict(manifest.base_map)
    for skill_id in active_skill_ids:
        skill_defs, skill_map = manifest.by_skill.get(skill_id, ([], {}))
        defs.extend(skill_defs)
        tool_map.update(skill_map)
    return defs, tool_map


def _get_session_system_prompt(session_id: str) -> str:
    return _state._session_system_prompts.get(session_id, _state._BASE_SYSTEM_PROMPT)


def _get_session_skill_registry(session_id: str) -> list[dict]:
    return _state._session_skill_registries.get(session_id, _state._BASE_SKILL_REGISTRY)


def _get_autoloaded_session_skills(session_id: str) -> list[dict]:
    return get_autoload_skill_entries(_get_session_skill_registry(session_id))


def _get_skills_info_payload(session: Session, session_id: str) -> dict:
    return skills_info_payload(session, _get_session_skill_registry(session_id))


def _get_tools_info_payload(session_id: str) -> dict:
    return tools_info_payload(
        _get_session_tool_defs(session_id), _get_session_plugins(session_id)
    )


def _init_session_caches(session: Session, session_id: str) -> None:
    """Build per-session skill registry, tool set, and system prompt caches
    (idempotent — skips if already done).

    Skill registry is built before tool loading: tool loading needs the
    resolved skill id set to validate skill-scoped plugin namespaces against.
    """
    _ensure_session_dirs_reported(session, session_id)
    skills_path = (
        os.path.join(session.initial_cwd, "skills")
        if session.load_custom_skills_tools
        else None
    )
    custom_tools_path = (
        os.path.join(session.initial_cwd, "tools")
        if session.load_custom_skills_tools
        else None
    )
    if session_id not in _state._session_skill_registries:
        registry = build_skill_registry(custom_skills_path=skills_path)
        _state._session_skill_registries[session_id] = registry
        session.session_data["__skill_files__"] = registry
    else:
        registry = _state._session_skill_registries[session_id]
        session.session_data["__skill_files__"] = registry

    if session_id not in _state._session_tool_sets:
        if custom_tools_path:
            known_skill_ids = frozenset(e["id"] for e in registry)
            try:
                result = load_custom_tools(
                    tools_dir=custom_tools_path,
                    workspace_root=session.initial_cwd or None,
                    session_prefix=session_id[:8],
                    known_skill_ids=known_skill_ids,
                )
                manifest = manifest_from_custom_tools(result)
            except RuntimeError as exc:
                # Never fail silently — a resumed session with a broken custom
                # tool setup must be just as visible as a freshly-created one
                # (POST /api/sessions hard-fails on this same error). Surface
                # it to the client, then fall back to built-in-only tools so
                # an existing conversation isn't bricked.
                logger.error(
                    "Custom tool loading failed for session %s: %s", session_id, exc
                )
                _emit_and_log(
                    session_id,
                    "error",
                    {"message": f"Custom tool loading failed: {exc}"},
                )
                manifest = SessionToolManifest(
                    base_defs=list(ALL_TOOL_DEFINITIONS), base_map=dict(_TOOL_MAP)
                )
        else:
            manifest = SessionToolManifest(
                base_defs=list(ALL_TOOL_DEFINITIONS), base_map=dict(_TOOL_MAP)
            )
        _state._session_tool_sets[session_id] = manifest

    if session_id not in _state._session_system_prompts:
        autoload_entries = get_autoload_skill_entries(registry)
        _state._session_system_prompts[session_id] = build_system_prompt(
            starting_environment_info=_build_starting_environment_info(session),
            autoload_entries=autoload_entries,
            placeholders=_build_prompt_placeholders(session, session_id),
        )

    _state._session_project_config[session_id] = {
        "initial_cwd": session.initial_cwd,
    }

    # Track per-session CWD; only initialise if not already set so mid-session
    # navigation (change_pwd) survives across calls to _init_session_caches.
    if session_id not in _state._session_current_cwd:
        _state._session_current_cwd[session_id] = session.initial_cwd


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_session_info(session_id: str) -> Session | None:
    """Load a session's settings and flags without its turns (cheap).

    For callers that need the cwd, custom skills/tools flag or settings but
    not the conversation. The result can never be saved. Returns None if the
    session does not exist.
    """
    session = load_session_info_from_db(session_id)
    if session is None:
        return None
    _init_session_caches(session, session_id)
    return session


def _repair_orphaned_latest_turn(session_id: str, info: Session) -> None:
    """Repair the latest turn if a restart/crash left it open (see _load_session).

    For a cached session the index row says whether the latest turn is still
    open, so the full load only runs when there is something to repair.
    """
    if _state.has_active_turn_task(session_id):
        return
    if info.history_cache_compatible:
        last = load_last_turn_rows(session_id, 1)
        if not last or last[0]["completed"]:
            return
    _load_session(session_id)


def _memory_change_notifier(session_id: str):
    def _on_memory_change(key: str, event_type: str) -> None:
        try:
            keys = list_memory_keys(session_id)
            socketio.emit("session_memory_keys_update", {"keys": keys}, room=session_id)
            socketio.emit(
                "session_memory_key_event",
                {"key": key, "type": event_type},
                room=session_id,
            )
        except Exception as exc:
            logger.warning(
                "_on_memory_change error (key=%r, session_id=%r): %s",
                key,
                session_id,
                exc,
            )

    return _on_memory_change


def _load_session(session_id: str) -> Session:
    """Load a session with its turns, for the agent (see session_db_load.py).

    Changes to the result are written with the session_writes functions, at
    the place each change is made.
    """
    session = load_session_from_db(session_id)
    if session is None:
        # No such session yet: create it.
        session = Session(session_id=session_id)
        write_session_created(session_id, session)
    session.session_data["memory"] = SessionMemory(
        session_id, on_change=_memory_change_notifier(session_id)
    )
    _init_session_caches(session, session_id)

    # Repair a turn orphaned by a previous restart/crash — but only when no live
    # asyncio task owns this session (an active turn must be left untouched).
    if session.current_turn is not None and not _state.has_active_turn_task(session_id):
        write_repaired_turn(session_id, session)

    return session


def _delete_sessions(session_ids: list[str]) -> None:
    """Delete many sessions from MySQL, Redis and in-memory caches."""
    if not session_ids:
        return
    # A failed MySQL delete propagates (and leaves Redis and caches intact).
    delete_sessions(session_ids)

    r = _state._get_redis()
    keys = []
    for session_id in session_ids:
        from src.ui_connector.socket_handler_components import runtime_settings
        from src.ui_connector.heartbeat_daemon import forget_heartbeat_session

        runtime_settings.discard(session_id)
        forget_heartbeat_session(session_id)
        keys.extend([f"session:{session_id}:events", watermark_key(session_id)])
    if keys:
        r.delete(*keys)

    for session_id in session_ids:
        _state._session_tool_sets.pop(session_id, None)
        _state._session_system_prompts.pop(session_id, None)
        _state._session_skill_registries.pop(session_id, None)
        _state._session_project_config.pop(session_id, None)
        _state._session_current_cwd.pop(session_id, None)
        _state._session_costs.pop(session_id, None)
        _state._session_last_context_usage.pop(session_id, None)
        forget_restored_session(session_id)
        delete_session_scratchpad(session_id)


def _delete_session(session_id: str) -> None:
    """Delete all data for a session from MySQL, Redis and in-memory caches."""
    _delete_sessions([session_id])


def invalidate_redis_session_cache_on_startup() -> None:
    """Flush per-session Redis state at boot.

    Sessions are durable in MySQL; Redis only holds each session's catch-up
    log of socket events and its bookmark (event_log.py). Neither is valid
    across a restart (no turn survives one), so both are cleared. Durable
    session data is NOT deleted.
    """
    try:
        r = _state._get_redis()
        keys = list(r.scan_iter("session:*"))
        if keys:
            r.delete(*keys)
            logger.info("Flushed %s Redis session cache key(s) on startup.", len(keys))
        else:
            logger.info("No Redis session cache to flush.")
    except Exception as exc:
        logger.warning("Could not flush Redis session cache on startup: %s", exc)
