from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_append_to_variable",
        "description": (
            "Append a literal string to an existing persistent project memory "
            "variable, writing the result back to the same key. The key must "
            "hold a JSON string value (or be absent, treated as empty string). "
            "The text is appended to the decoded string content and the result "
            "is stored back as a JSON string. Does not work on numbers, "
            "objects, or arrays."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "The project memory key to read from and write back to. "
                        "The stored value must be a JSON string (or absent, "
                        "treated as empty string)."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The literal text to append to the decoded JSON string "
                        "value. This is a raw string, not a JSON-encoded value."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    ),
                },
            },
            "required": ["key", "text"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def execute(args: dict, _session_data: dict | None = None) -> str:
    key = args["key"]
    text = args["text"]
    project = args.get("project", os.getcwd())
    pool = get_pool()
    with pool.get_connection() as conn:
        manager = KVManager(conn, project)
        manager.set_value(key, _as_text(manager.get_value(key)) + text)
        conn.commit()
    return f"Appended text to {key}"
