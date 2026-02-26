from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_set_variable",
        "description": (
            "Set a persistent project memory value. "
            "Project memory persists across sessions and is scoped to a project path. "
            "Provide either a literal 'value' string or a 'from_session_key' to copy "
            "from session memory — not both."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to store.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the pinned initial working directory (or current "
                        "working directory if pinning is disabled)."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The literal text value to store. Mutually exclusive with from_session_key.",
                },
                "from_session_key": {
                    "type": "string",
                    "description": (
                        "Copy the value from this session memory key into project memory. "
                        "Mutually exclusive with value. "
                        "Use this after editing content in session memory to persist it."
                    ),
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _get_project(args: dict, session_data: dict) -> str:
    explicit = args.get("project")
    if explicit:
        return explicit
    pinned = (session_data or {}).get("__pinned_project__")
    if pinned:
        return pinned
    return os.getcwd()


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    key = args["key"]
    project = _get_project(args, session_data)

    has_value = "value" in args
    has_from = "from_session_key" in args

    if has_value and has_from:
        return "Error: provide either 'value' or 'from_session_key', not both."
    if not has_value and not has_from:
        return "Error: provide either 'value' or 'from_session_key'."

    if has_from:
        session_key = args["from_session_key"]
        memory = (session_data or {}).get("memory", {})
        if not isinstance(memory, dict) or session_key not in memory:
            return f"Error: session memory key {session_key!r} not found."
        text = memory[session_key]
        if not isinstance(text, str):
            return f"Error: session memory key {session_key!r} does not hold a text value."
    else:
        text = args["value"]
        if not isinstance(text, str):
            return f"Error: value must be a plain string, got {type(text).__name__}."

    pool = get_pool()
    with pool.get_connection() as conn:
        KVManager(conn).set_value(key, text, project=project)
        conn.commit()

    return f"Stored value at project memory key {key!r}."
