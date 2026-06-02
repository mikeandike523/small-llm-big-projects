from __future__ import annotations

import json
import logging
import os
from collections import deque

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.terminal import (
    _build_starting_environment_info,
)
from src.tools import ALL_TOOL_DEFINITIONS, _TOOL_MAP, load_custom_tools
from src.logic.system_prompt import (
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)
from src.utils.redis_dict import RedisDict
from src.utils.session_model import (
    Session,
    session_to_dict,
    session_from_dict,
    CURRENT_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session cache accessors
# ---------------------------------------------------------------------------


def _get_session_tool_defs(session_id: str) -> list[dict]:
    return _state._session_tool_sets.get(
        session_id, (ALL_TOOL_DEFINITIONS, _TOOL_MAP, [])
    )[0]


def _get_session_tool_map(session_id: str) -> dict:
    return _state._session_tool_sets.get(
        session_id, (ALL_TOOL_DEFINITIONS, _TOOL_MAP, [])
    )[1]


def _get_session_plugins(session_id: str) -> list[dict]:
    return _state._session_tool_sets.get(
        session_id, (ALL_TOOL_DEFINITIONS, _TOOL_MAP, [])
    )[2]


def _get_session_system_prompt(session_id: str) -> str:
    return _state._session_system_prompts.get(session_id, _state._BASE_SYSTEM_PROMPT)


def _get_session_skill_registry(session_id: str) -> list[dict]:
    return _state._session_skill_registries.get(session_id, _state._BASE_SKILL_REGISTRY)


def _get_autoloaded_session_skills(session_id: str) -> list[dict]:
    return get_autoload_skill_entries(_get_session_skill_registry(session_id))


def _init_session_caches(session: Session, session_id: str) -> None:
    """Build per-session tool set and system prompt caches (idempotent — skips if already done)."""
    if session_id not in _state._session_tool_sets:
        if session.custom_tools_path:
            try:
                extra_defs, extra_map, plugins, custom_exclusions = load_custom_tools(
                    tools_dir=session.custom_tools_path,
                    workspace_root=session.initial_cwd or None,
                    session_prefix=session_id[:8],
                )
                _excl_load = {n for n, f in custom_exclusions.items() if f.get("loading")}
                base_defs = [d for d in ALL_TOOL_DEFINITIONS if d.get("function", {}).get("name") not in _excl_load]
                base_map = {k: v for k, v in _TOOL_MAP.items() if k not in _excl_load}
                tool_defs = base_defs + extra_defs
                tool_map = {**base_map, **extra_map}
            except RuntimeError as exc:
                logger.error(
                    "Custom tool loading failed for session %s: %s", session_id, exc
                )
                tool_defs = list(ALL_TOOL_DEFINITIONS)
                tool_map = dict(_TOOL_MAP)
                plugins = []
        else:
            tool_defs = ALL_TOOL_DEFINITIONS
            tool_map = _TOOL_MAP
            plugins = []
        _state._session_tool_sets[session_id] = (tool_defs, tool_map, plugins)

    if session_id not in _state._session_skill_registries:
        registry = build_skill_registry(custom_skills_path=session.skills_path)
        _state._session_skill_registries[session_id] = registry
        session.session_data["__skill_files__"] = registry
    else:
        registry = _state._session_skill_registries[session_id]
        session.session_data["__skill_files__"] = registry

    if session_id not in _state._session_system_prompts:
        autoload_entries = get_autoload_skill_entries(registry)
        _state._session_system_prompts[session_id] = build_system_prompt(
            starting_environment_info=_build_starting_environment_info(session),
            autoload_entries=autoload_entries,
        )

    _state._session_project_config[session_id] = {
        "initial_cwd": session.initial_cwd,
    }

    # Track per-session CWD; only initialise if not already set so mid-session
    # navigation (change_pwd) survives across calls to _init_session_caches.
    if session_id not in _state._session_current_cwd:
        _state._session_current_cwd[session_id] = session.initial_cwd

    # Re-create the trace buffer if the session was loaded from Redis after a restart.
    if session.record_traces and session_id not in _state._session_trace_buffers:
        _state._session_trace_buffers[session_id] = deque()


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


def _load_session(session_id: str) -> Session:
    r = _state._get_redis()
    raw = r.get(f"session:{session_id}")
    if raw:
        try:
            d = json.loads(raw)
            if d.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
                session = Session(session_id=session_id)
            else:
                session = session_from_dict(d)
        except Exception:
            session = Session(session_id=session_id)
    else:
        session = Session(session_id=session_id)

    mem_hash_key = f"session:{session_id}:memory"

    def _on_memory_change(key: str, event_type: str) -> None:
        try:
            keys = r.hkeys(mem_hash_key)
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

    session.session_data["memory"] = RedisDict(
        r, mem_hash_key, on_change=_on_memory_change
    )
    _init_session_caches(session, session_id)
    return session


def _save_session(session_id: str, session: Session) -> None:
    r = _state._get_redis()
    blob = session_to_dict(session)
    r.setex(f"session:{session_id}", _state._SESSION_TTL, json.dumps(blob))
    r.expire(f"session:{session_id}:memory", _state._SESSION_TTL)
    r.expire(f"session:{session_id}:events", _state._SESSION_TTL)


def _delete_session(session_id: str) -> None:
    """Delete all data for a session from Redis and in-memory caches."""
    r = _state._get_redis()
    r.delete(f"session:{session_id}")
    r.delete(f"session:{session_id}:memory")
    r.delete(f"session:{session_id}:events")
    _state._session_tool_sets.pop(session_id, None)
    _state._session_system_prompts.pop(session_id, None)
    _state._session_skill_registries.pop(session_id, None)
    _state._session_project_config.pop(session_id, None)
    _state._session_current_cwd.pop(session_id, None)
    _state._session_trace_buffers.pop(session_id, None)
    _state._session_costs.pop(session_id, None)


def clear_all_sessions_on_startup() -> None:
    """Delete every session:* key from Redis at server startup to avoid stale data."""
    try:
        r = _state._get_redis()
        keys = list(r.scan_iter("session:*"))
        if keys:
            r.delete(*keys)
            logger.info("Cleared %s stale session key(s) from Redis.", len(keys))
        else:
            logger.info("No stale sessions to clear.")
    except Exception as exc:
        logger.warning("Could not clear sessions on startup: %s", exc)
