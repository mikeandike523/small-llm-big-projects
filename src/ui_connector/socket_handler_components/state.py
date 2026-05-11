from __future__ import annotations

import asyncio
import os
import threading
from collections import deque

import redis

from src.terminal import TerminalSessionManager
from src.utils.env_info import get_os, get_shell
from src.utils.docker_compose import get_service_port
from src.logic.system_prompt import build_skill_registry, build_system_prompt, get_autoload_skill_entries

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

# Trace recording config (set by slbp server run)
_server_cwd: str = os.environ.get("SLBP_SERVER_CWD", os.getcwd())
_traces_dir: str = os.path.join(_server_cwd, ".slbp-traces")
_trace_folder_max_bytes: int | None = (
    int(float(os.environ["SLBP_TRACE_FOLDER_MAX_GB"]) * 1024 ** 3)
    if "SLBP_TRACE_FOLDER_MAX_GB" in os.environ
    else None
)

# ---------------------------------------------------------------------------
# Per-session state caches (rebuilt from session data on load)
# ---------------------------------------------------------------------------

# session_id -> (tool_definitions, tool_map, plugin_info_list)
_session_tool_sets: dict[str, tuple[list, dict, list]] = {}
# session_id -> system_prompt_string
_session_system_prompts: dict[str, str] = {}
# session_id -> list of skill descriptors
_session_skill_registries: dict[str, list[dict]] = {}
# session_id -> {initial_cwd} — lightweight cache for info handlers
_session_project_config: dict[str, dict] = {}
# session_id -> current working directory for this session (updated by change_pwd tool)
_session_current_cwd: dict[str, str] = {}
# session_id -> deque of TraceEntry objects (only populated when session.record_traces=True)
_session_trace_buffers: dict[str, deque] = {}
# session_id -> accumulated cost in USD for this session
_session_costs: dict[str, float] = {}
# Set of session_ids that are currently executing a turn
_session_active_turns: set[str] = set()

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

# Asyncio cancellation: maps session_id -> (event_loop, asyncio.Task)
_cancel_loops: dict[str, asyncio.AbstractEventLoop] = {}
_cancel_tasks: dict[str, asyncio.Task] = {}

# ---------------------------------------------------------------------------
# Backend log counter
# ---------------------------------------------------------------------------

_log_counter = 0
_log_counter_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# Maps socket session ID to {"event": threading.Event, "approved": bool | None}
_pending_approvals: dict[str, dict] = {}

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
    "record_traces":                False,
    "load_skills":                  False,
    "load_tools":                   False,
    "load_startup_tool_calls":      False,
}

# Maps DB param key (as stored in kv_store) -> session defaults key
_SESSION_DEFAULTS_FROM_DB: dict[str, str] = {
    "params.model.irat": "interim_response_as_thinking",
}

# ---------------------------------------------------------------------------
# Misc constants
# ---------------------------------------------------------------------------

_OPENAI_MESSAGE_KEYS: frozenset[str] = frozenset(
    {"role", "content", "tool_calls", "tool_call_id", "name"}
)

_CONTEXT_LIMIT_KEYWORDS = (
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "maximum token",
    "context window",
    "too many tokens",
    "input is too long",
    "prompt is too long",
    "exceeds the maximum",
)

TITLE_MAX_CHARS = 80

_SKILL_SELECTOR_TURN_CHARS = 600
