from __future__ import annotations

import json
import logging
import os

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
    repair_incomplete_turn,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.session_events import derive_meta, replay_events
from src.utils.sql.session_store_db import (
    append_events,
    delete_session,
    load_session_events,
    load_session_meta,
    mark_session_corrupt,
    upsert_session_meta,
)
from src.ui_connector.socket_handler_components._session_event_emit import (
    build_cursor,
    compute_events,
    load_cursor,
    save_cursor,
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


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


def _session_from_db(session_id: str) -> Session | None:
    """Load a session from the durable MySQL store (cache miss path).

    Reconstructs the Session by replaying its event log, rehydrates the Redis
    memory hash from the metadata row, restores the Python-memory state (current
    cwd, accumulated cost), and resyncs the persist cursor so the next save emits
    only genuine deltas (the Redis cursor is gone on a cold load). Returns None if
    there is no durable session (caller then creates a fresh Session).
    """
    try:
        meta = load_session_meta(session_id)
    except Exception as exc:
        logger.warning("DB load failed for session %s: %s", session_id, exc)
        return None
    if meta is None:
        return None

    if meta.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
        return Session(session_id=session_id)

    r = _state._get_redis()
    try:
        rows = load_session_events(session_id)
        session = replay_events(session_id, rows)
        # Resync the cursor with the durable log (prevents duplicate re-emits).
        save_cursor(r, session_id, build_cursor(session), _state._SESSION_TTL)
    except Exception as exc:
        logger.warning("Could not replay DB session %s: %s", session_id, exc)
        try:
            mark_session_corrupt(session_id)
        except Exception:
            pass
        return Session(session_id=session_id)

    # Rehydrate the session_memory hash into Redis so the RedisDict sees it.
    mem_hash_key = f"session:{session_id}:memory"
    memory = meta.get("memory") or {}
    r.delete(mem_hash_key)
    if memory:
        r.hset(mem_hash_key, mapping=memory)

    # Restore Python-memory-only state.
    if meta.get("current_cwd"):
        _state._session_current_cwd[session_id] = meta["current_cwd"]
    if meta.get("total_cost_usd"):
        _state._session_costs[session_id] = float(meta["total_cost_usd"])

    return session


def _load_session(session_id: str) -> Session:
    r = _state._get_redis()
    raw = r.get(f"session:{session_id}")
    cold = False
    if raw:
        try:
            d = json.loads(raw)
            if d.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
                session = Session(session_id=session_id)
            else:
                session = session_from_dict(d)
        except Exception:
            session = Session(session_id=session_id)
        # The warm blob reflects the last save; if the persist cursor was evicted
        # independently, rebuild it so the next save doesn't re-emit every event.
        if not load_cursor(r, session_id):
            save_cursor(r, session_id, build_cursor(session), _state._SESSION_TTL)
    else:
        # Redis cache miss -> durable load from MySQL (e.g. after a restart).
        cold = True
        session = _session_from_db(session_id) or Session(session_id=session_id)

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

    # Repair a turn orphaned by a previous restart/crash — but only when no live
    # asyncio task owns this session (an active turn must be left untouched).
    needs_persist = False
    if session.current_turn is not None and session_id not in _state._cancel_tasks:
        needs_persist = repair_incomplete_turn(session)

    # A cold (DB) load must warm the Redis cache; a repair must be persisted.
    if cold or needs_persist:
        _save_session(session_id, session)

    return session


def _save_session(session_id: str, session: Session) -> None:
    """Persist a session: append new events + upsert metadata (MySQL, durable),
    then warm the Redis cache.

    Events are derived by diffing the in-memory Session against the persist
    cursor, so only new/changed state is appended. Writing MySQL first keeps the
    durable copy authoritative if the process dies mid-save; the Redis blob is
    just a hot cache (flushed and rebuilt from the event log on boot).
    """
    r = _state._get_redis()
    blob = session_to_dict(session)

    # Durable write to MySQL (source of truth).
    try:
        memory_snapshot = r.hgetall(f"session:{session_id}:memory") or {}
        cursor = load_cursor(r, session_id)
        events = compute_events(session, cursor)
        if events:
            append_events(session_id, events)
        save_cursor(r, session_id, cursor, _state._SESSION_TTL)

        meta = derive_meta(session)
        upsert_session_meta(
            session_id,
            created_at=session.created_at,
            schema_version=session.schema_version,
            profile_name=session.profile_name,
            initial_cwd=session.initial_cwd or "",
            current_cwd=_state._session_current_cwd.get(session_id),
            total_cost_usd=float(_state._session_costs.get(session_id) or 0.0),
            turn_count=meta["turn_count"],
            task_titles=meta["task_titles"],
            interim_response_as_thinking=session.interim_response_as_thinking,
            skills_path=session.skills_path,
            custom_tools_path=session.custom_tools_path,
            memory=memory_snapshot,
        )
    except Exception as exc:
        logger.warning("DB save failed for session %s: %s", session_id, exc)

    # Warm Redis cache (TTL is now just eviction; data survives in MySQL).
    r.setex(f"session:{session_id}", _state._SESSION_TTL, json.dumps(blob))
    r.expire(f"session:{session_id}:memory", _state._SESSION_TTL)
    r.expire(f"session:{session_id}:events", _state._SESSION_TTL)


def _delete_session(session_id: str) -> None:
    """Delete all data for a session from MySQL, Redis and in-memory caches."""
    try:
        delete_session(session_id)
    except Exception as exc:
        logger.warning("DB delete failed for session %s: %s", session_id, exc)
    r = _state._get_redis()
    r.delete(f"session:{session_id}")
    r.delete(f"session:{session_id}:memory")
    r.delete(f"session:{session_id}:events")
    r.delete(f"session:{session_id}:persist_state")
    _state._session_tool_sets.pop(session_id, None)
    _state._session_system_prompts.pop(session_id, None)
    _state._session_skill_registries.pop(session_id, None)
    _state._session_project_config.pop(session_id, None)
    _state._session_current_cwd.pop(session_id, None)
    _state._session_costs.pop(session_id, None)


def invalidate_redis_session_cache_on_startup() -> None:
    """Flush the Redis session cache at boot so it rehydrates from MySQL.

    Sessions are now durable in MySQL (the `sessions` table); Redis only acts as
    a hot write-through cache plus the live event/memory stores. Flushing the
    cache on boot avoids serving a stale blob that may be inconsistent with the
    durable copy (e.g. if the process died between the MySQL and Redis writes).
    Durable session data is NOT deleted.
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
