from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_delete_variable",
        "description": (
            "Delete a persistent project memory key for the current project (or a specified one)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to delete.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the pinned initial working directory (or current "
                        "working directory if pinning is disabled)."
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

    pool = get_pool()
    with pool.get_connection() as conn:
        manager = KVManager(conn)
        existed = manager.exists(key, project=project)
        manager.delete_value(key, project=project)
        conn.commit()

    if existed:
        return f"Deleted project memory key {key!r}."
    return f"Key {key!r} was not found in project memory."
