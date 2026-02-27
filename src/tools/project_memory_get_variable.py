from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 500

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_get_variable",
        "description": (
            "Get a persistent project memory value. "
            "Project memory persists across sessions and is scoped to a project path. "
            "Use target='return_value' (default) to get the value inline, or "
            "target='session_memory' with a target_session_key to load it into session "
            "memory for manipulation with session memory tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The project memory key to fetch.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the pinned initial working directory (or current "
                        "working directory if pinning is disabled)."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "'return_value' (default): return the value inline. "
                        "'session_memory': write the value into a session memory key "
                        "(requires target_session_key). Useful for large values you want "
                        "to manipulate with session memory tools before saving back."
                    ),
                },
                "target_session_key": {
                    "type": "string",
                    "description": (
                        "Required when target='session_memory'. "
                        "The session memory key to write the fetched value into."
                    ),
                },
                "number_lines": {
                    "type": "boolean",
                    "description": (
                        "If true, return a line-numbered view of the value. "
                        "Only applies when target='return_value'."
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


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    key = args["key"]
    project = _get_project(args, session_data)
    target = args.get("target", "return_value")

    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)

    if value is None:
        return f"(key {key!r} not found in project memory)"

    if target == "session_memory":
        session_key = args.get("target_session_key")
        if not session_key:
            return "Error: target='session_memory' requires target_session_key."
        memory = _ensure_session_memory(session_data)
        memory[session_key] = value
        return f"Loaded project memory key {key!r} into session memory key {session_key!r}."

    if args.get("number_lines"):
        if not isinstance(value, str):
            return f"Error: key {key!r} does not hold a text value."
        return add_line_numbers(value, start_line=1)

    return value
