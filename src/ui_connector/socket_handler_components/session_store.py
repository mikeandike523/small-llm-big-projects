from __future__ import annotations

import logging
import os

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import _emit_and_log
from src.ui_connector.socket_handler_components.terminal import (
    _build_starting_environment_info,
)
from src.ui_connector.socket_handler_components.state import SessionToolManifest
from src.tools import ALL_TOOL_DEFINITIONS, _TOOL_MAP, load_custom_tools
from src.logic.system_prompt import (
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)
from src.utils.event_log import (
    latest_stream_id,
    set_watermark,
    trim_stream_upto,
    watermark_key,
)
from src.utils.redis_dict import RedisDict
from src.utils.session_model import (
    Session,
    repair_incomplete_turn,
    CURRENT_SCHEMA_VERSION,
)
from src.utils.session_events import derive_meta, replay_events
from src.utils.session_schema_repair import repair_event_log
from src.utils.sql.session_store_db import (
    append_events,
    delete_sessions,
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


def _live_marker_key(session_id: str) -> str:
    return f"session:{session_id}:live"


def _session_from_db(session_id: str, *, cold: bool) -> Session | None:
    """Load a session from the durable MySQL store by replaying its event log.

    Every load goes through here: MySQL is the only source of the session model
    (there is no whole-session Redis copy). Each call returns an independent
    Session object.

    `cold` means this process's live Redis state for the session is gone (boot
    flush or TTL expiry). Only then is the memory hash rehydrated from the
    metadata row, the Python-memory state (current cwd, accumulated cost,
    context usage) restored, and the persist cursor rebuilt. A warm load must
    not touch those: they may hold live, not-yet-saved state. Returns None if
    there is no durable session (caller then creates a fresh Session).
    """
    try:
        meta = load_session_meta(session_id)
    except Exception as exc:
        logger.warning("DB load failed for session %s: %s", session_id, exc)
        return None
    if meta is None:
        return None

    r = _state._get_redis()
    try:
        rows = load_session_events(session_id)
        if meta.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
            # See session_schema_repair.py: a registered chain can rewrite
            # meta/rows forward to the current shape; if none is registered
            # for this version gap (the common case today), fall back to a
            # blank session rather than replaying a shape replay_events()
            # wasn't written to understand.
            repaired = repair_event_log(meta, rows, CURRENT_SCHEMA_VERSION)
            if repaired is None:
                return Session(session_id=session_id)
            meta, rows = repaired
        session = replay_events(session_id, rows)
        # Resync the cursor with the durable log (prevents duplicate re-emits).
        if cold or not load_cursor(r, session_id):
            save_cursor(r, session_id, build_cursor(session), _state._SESSION_TTL)
    except Exception as exc:
        logger.warning("Could not replay DB session %s: %s", session_id, exc)
        try:
            mark_session_corrupt(session_id)
        except Exception:
            pass
        return Session(session_id=session_id)

    if not cold:
        return session

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
    if meta.get("last_context_usage"):
        last_context_usage = meta["last_context_usage"]
        # The snapshot is stamped with the profile that produced it. If the
        # profile changed between runs (e.g. switched after a restart), the
        # stored token counts and known_max_context no longer describe the
        # current profile — drop the stale snapshot instead of restoring it
        # (the next _save_session then writes NULL to session_meta, and the
        # next main-agent exchange with a max-context profile re-emits fresh).
        if last_context_usage.get("profile") == session.profile_name:
            # Runtime revisions intentionally restart with the server. No old
            # request can still be in flight after a cold load, so rebase the
            # durable snapshot onto the new runtime generation.
            last_context_usage["profile_revision"] = 0
            _state._session_last_context_usage[session_id] = last_context_usage
        else:
            _state._session_last_context_usage.pop(session_id, None)
            logger.info(
                "Dropping stale last_context_usage for session %s "
                "(snapshot profile %r != current profile %r)",
                session_id,
                last_context_usage.get("profile"),
                session.profile_name,
            )

    return session


def _load_session(session_id: str) -> Session:
    r = _state._get_redis()
    cold = not r.exists(_live_marker_key(session_id))
    session = _session_from_db(session_id, cold=cold) or Session(session_id=session_id)
    r.setex(_live_marker_key(session_id), _state._SESSION_TTL, "1")

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
    if session.current_turn is not None and not _state.has_active_turn_task(session_id):
        needs_persist = repair_incomplete_turn(session)

    # A cold load refreshes the metadata row (and creates it for a brand-new
    # session); a repair must be persisted.
    if cold or needs_persist:
        _save_session(session_id, session)

    return session


def _save_session(
    session_id: str, session: Session, *, advance_stream_watermark: bool = False
) -> None:
    """Serialize cursor/event/meta writes for one session.

    `advance_stream_watermark` is passed ONLY by the agent loop's step-boundary
    saves (each follows a whole-exchange append, or the turn's end). There every
    socket event logged so far describes state that this save makes durable, so
    the Redis event log's bookmark can move past them. Any other save (title,
    settings endpoints, repair) may run mid-step on a different Session copy
    and must leave the bookmark alone.
    """
    from src.ui_connector.socket_handler_components import runtime_settings

    with runtime_settings.persistence_lock(session_id):
        _save_session_locked(session_id, session, advance_stream_watermark)


def _save_session_locked(
    session_id: str, session: Session, advance_stream_watermark: bool = False
) -> None:
    """Persist a session: append new events + upsert metadata (MySQL, durable).

    Events are derived by diffing the in-memory Session against the persist
    cursor, so only new/changed state is appended. MySQL is the only store of
    the session model; nothing serializes the whole session.
    """
    from src.ui_connector.socket_handler_components import runtime_settings

    runtime_settings.merge_into_session(session_id, session)
    r = _state._get_redis()
    # Read before the diff: every event logged up to here is covered by it.
    stream_mark = latest_stream_id(r, session_id) if advance_stream_watermark else None

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
            last_context_usage=_state._session_last_context_usage.get(session_id),
            turn_count=meta["turn_count"],
            task_titles=meta["task_titles"],
            interim_response_as_thinking=session.interim_response_as_thinking,
            load_custom_skills_tools=session.load_custom_skills_tools,
            memory=memory_snapshot,
            heartbeat_enabled=bool(
                (session.session_data.get("heartbeat_settings") or {}).get("enabled")
            ),
        )
    except Exception as exc:
        logger.warning("DB save failed for session %s: %s", session_id, exc)
    else:
        if stream_mark is not None:
            # Only after a successful durable write: the logged events up to
            # the mark are now in MySQL, so drop them from the Redis log.
            set_watermark(r, session_id, stream_mark, _state._SESSION_TTL)
            trim_stream_upto(r, session_id, stream_mark)

    r.expire(f"session:{session_id}:memory", _state._SESSION_TTL)
    r.expire(f"session:{session_id}:events", _state._SESSION_TTL)
    r.setex(_live_marker_key(session_id), _state._SESSION_TTL, "1")


def _delete_sessions(session_ids: list[str]) -> None:
    """Delete many sessions from MySQL, Redis and in-memory caches."""
    if not session_ids:
        return
    try:
        delete_sessions(session_ids)
    except Exception as exc:
        logger.warning("DB delete failed for sessions %s: %s", session_ids, exc)

    r = _state._get_redis()
    keys = []
    for session_id in session_ids:
        from src.ui_connector.socket_handler_components import runtime_settings
        from src.ui_connector.heartbeat_daemon import forget_heartbeat_session

        runtime_settings.discard(session_id)
        forget_heartbeat_session(session_id)
        keys.extend(
            [
                _live_marker_key(session_id),
                f"session:{session_id}:memory",
                f"session:{session_id}:events",
                watermark_key(session_id),
                f"session:{session_id}:persist_state",
            ]
        )
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


def _delete_session(session_id: str) -> None:
    """Delete all data for a session from MySQL, Redis and in-memory caches."""
    _delete_sessions([session_id])


def invalidate_redis_session_cache_on_startup() -> None:
    """Flush per-session Redis state at boot so it rehydrates from MySQL.

    Sessions are durable in MySQL (`session_meta` + `session_events`); Redis
    only holds live per-process state: the memory hash, the persist cursor, the
    live marker, and the unsaved-event log with its bookmark. None of it is
    valid across a restart (no turn survives one), so it is cleared and the
    first load of each session is cold. Durable session data is NOT deleted.
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
