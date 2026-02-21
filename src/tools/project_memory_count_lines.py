from __future__ import annotations

import json
import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_count_lines",
        "description": (
            "Count lines in a project memory item. Requires the stored value "
            "to be a JSON string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to count lines for.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
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


def _count_lines(text: str) -> int:
    if text == "":
        return 0
    newline_count = text.count("\n")
    if text.endswith("\n"):
        return newline_count
    return newline_count + 1


def execute(args: dict, _session_data: dict | None = None) -> str:
    key = args["key"]
    project = args.get("project", os.getcwd())

    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn, project).get_value(key)

    if not isinstance(value, str):
        return f"key {key} is not a json string"

    return json.dumps({"line_count": _count_lines(value)}, ensure_ascii=False)
