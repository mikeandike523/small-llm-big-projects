from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_concat",
        "description": (
            "Concatenate two persistent memory values scoped to the current "
            "project or a specified project, then save to a destination key."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key_a": {
                    "type": "string",
                    "description": "The first memory key to read.",
                },
                "key_b": {
                    "type": "string",
                    "description": "The second memory key to read.",
                },
                "dest_key": {
                    "type": "string",
                    "description": "The destination memory key to write.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    ),
                },
            },
            "required": ["key_a", "key_b", "dest_key"],
            "additionalProperties": False,
        },
    },
}


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def execute(args: dict, _session_data: dict | None = None) -> str:
    key_a = args["key_a"]
    key_b = args["key_b"]
    dest_key = args["dest_key"]
    project = args.get("project", os.getcwd())
    pool = get_pool()
    with pool.get_connection() as conn:
        manager = KVManager(conn, project)
        value_a = _as_text(manager.get_value(key_a))
        value_b = _as_text(manager.get_value(key_b))
        manager.set_value(dest_key, value_a + value_b)
        conn.commit()
    return f"Concatted {key_a} and {key_b} and saved to {dest_key}"
