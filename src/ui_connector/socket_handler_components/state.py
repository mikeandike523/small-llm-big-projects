from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field

import redis

from src.terminal import TerminalSessionManager
from src.utils.env_info import get_os, get_shell
from src.utils.session_model import SUBTURN_ORIGIN_USER
from src.utils.docker_compose import get_service_port
from src.logic.system_prompt import (
    build_skill_registry,
    build_system_prompt,
    get_autoload_skill_entries,
)


@dataclass
class SessionToolManifest:
    """A session's fully-validated custom tool set, grouped by activation scope.

    base_defs/base_map: built-ins (minus load exclusions) + unscoped custom
    tools — always included in every subturn's active tool set.
    by_skill: skill_id -> (defs, tool_map) for each skill-scoped plugin —
    only included in a subturn where that skill id is active.
    plugins: debug-panel-facing plugin info ({name, count, path}).
    """

    base_defs: list[dict] = field(default_factory=list)
    base_map: dict = field(default_factory=dict)
    by_skill: dict[str, tuple[list[dict], dict]] = field(default_factory=dict)
    plugins: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Base skill registry and system prompt (built once at server start)
# ---------------------------------------------------------------------------

_BASE_SKILL_REGISTRY: list[dict] = build_skill_registry()
_BASE_SYSTEM_PROMPT: str = build_system_prompt(
    autoload_entries=get_autoload_skill_entries(_BASE_SKILL_REGISTRY),
)

_env_os = get_os()
_env_shell = get_shell()
_hotfix_bad_parser: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER") == "1"
_hotfix_void_call: bool = os.environ.get("SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL") == "1"

# ---------------------------------------------------------------------------
# Per-session state caches (rebuilt from session data on load)
# ---------------------------------------------------------------------------

# session_id -> SessionToolManifest
_session_tool_sets: dict[str, SessionToolManifest] = {}
# session_id -> system_prompt_string
_session_system_prompts: dict[str, str] = {}
# session_id -> list of skill descriptors
_session_skill_registries: dict[str, list[dict]] = {}
# session_id -> {initial_cwd} — lightweight cache for info handlers
_session_project_config: dict[str, dict] = {}
# session_id -> current working directory for this session (updated by change_pwd tool)
_session_current_cwd: dict[str, str] = {}
# session_id -> accumulated cost in USD for this session
_session_costs: dict[str, float] = {}
# session_id -> last context usage snapshot emitted by the MAIN agent exchange
# loop ({"prompt_tokens", "completion_tokens", "total_tokens", "known_max_context"}).
# Telemetry (like cost, NOT event-sourced); flushed to session_meta on save.
_session_last_context_usage: dict[str, dict] = {}
# Atomic admission state for user-message turns. This reservation begins before
# preprocessing and outlives the asyncio cancellation handles below. The value
# is the origin (owner) of the subturn being run: SUBTURN_ORIGIN_USER or
# SUBTURN_ORIGIN_HEARTBEAT.
_turn_reservations: dict[str, str] = {}
_turn_reservations_lock = threading.Lock()


def try_reserve_turn(session_id: str, origin: str = SUBTURN_ORIGIN_USER) -> bool:
    """Atomically admit one user-message operation for a session."""
    with _turn_reservations_lock:
        if session_id in _turn_reservations:
            return False
        _turn_reservations[session_id] = origin
        return True


def release_turn(session_id: str) -> None:
    """Release a previously admitted user-message operation."""
    with _turn_reservations_lock:
        _turn_reservations.pop(session_id, None)


def is_turn_reserved(session_id: str) -> bool:
    """Return the authoritative process-local active-turn status."""
    with _turn_reservations_lock:
        return session_id in _turn_reservations


def reserved_turn_origin(session_id: str) -> str | None:
    """Return who owns the session's running subturn, or None when idle."""
    with _turn_reservations_lock:
        return _turn_reservations.get(session_id)


# ---------------------------------------------------------------------------
# Terminal state
# ---------------------------------------------------------------------------

_terminal_manager = TerminalSessionManager()
_terminal_output_threads: dict[str, threading.Thread] = {}
_terminal_session_rooms: dict[str, str] = {}
_terminal_id_lock = threading.Lock()
# terminal_id -> "agent" | "user"
_terminal_opened_by: dict[str, str] = {}
# session_id -> {agent_last_opened, user_last_opened, active, last_asked}
_session_terminal_state_meta: dict[str, dict] = {}
_TERMINAL_SENTINELS = {"agent_last_opened", "user_last_opened", "active", "last_asked"}

# ---------------------------------------------------------------------------
# SID → session_id mapping (cleaned up on disconnect, NOT on session end)
# ---------------------------------------------------------------------------

_sid_to_session_id: dict[str, str] = {}

# Active turn cancellation handles, keyed by session_id. These are not the
# authoritative busy state: they exist only while the asyncio task exists.
_active_turn_loops: dict[str, asyncio.AbstractEventLoop] = {}
_active_turn_tasks: dict[str, asyncio.Task] = {}
_active_turn_handles_lock = threading.Lock()


def register_active_turn_handles(
    session_id: str,
    loop: asyncio.AbstractEventLoop,
    task: asyncio.Task,
) -> None:
    with _active_turn_handles_lock:
        _active_turn_loops[session_id] = loop
        _active_turn_tasks[session_id] = task


def get_active_turn_handles(
    session_id: str,
) -> tuple[asyncio.AbstractEventLoop | None, asyncio.Task | None]:
    with _active_turn_handles_lock:
        return (
            _active_turn_loops.get(session_id),
            _active_turn_tasks.get(session_id),
        )


def has_active_turn_task(session_id: str) -> bool:
    """Return whether the admitted turn currently has an asyncio task."""
    with _active_turn_handles_lock:
        return session_id in _active_turn_tasks


def clear_active_turn_handles(session_id: str, task: asyncio.Task) -> None:
    """Remove cancellation handles only when they still belong to this task."""
    with _active_turn_handles_lock:
        if _active_turn_tasks.get(session_id) is not task:
            return
        _active_turn_tasks.pop(session_id, None)
        _active_turn_loops.pop(session_id, None)


# ---------------------------------------------------------------------------
# Backend log counter
# ---------------------------------------------------------------------------

_log_counter = 0
_log_counter_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# Maps session_id (NOT the Socket.IO connection sid — that's transient and
# changes on every reconnect) to {"event": threading.Event, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}
_pending_approvals_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

_redis_client: redis.Redis | None = None
_SESSION_TTL = 3600


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=get_service_port("redis", 6379),
            decode_responses=True,
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Session defaults — single source of truth for new-session option defaults.
# ---------------------------------------------------------------------------

_SESSION_DEFAULTS_HARDCODED: dict = {
    "interim_response_as_thinking": False,
    "load_custom_skills_tools": False,
    "load_startup_tool_calls": False,
}

# Maps DB param key (as stored in kv_store) -> session defaults key
_SESSION_DEFAULTS_FROM_DB: dict[str, str] = {
    "params.model.irat": "interim_response_as_thinking",
}

# ---------------------------------------------------------------------------
# Misc constants
# ---------------------------------------------------------------------------

_OPENAI_MESSAGE_KEYS: frozenset[str] = frozenset(
    {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_native"}
)

TITLE_MAX_CHARS = 80

_SKILL_SELECTOR_TURN_CHARS = 600
