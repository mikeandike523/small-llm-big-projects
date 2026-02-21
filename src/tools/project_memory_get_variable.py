from __future__ import annotations

import json
import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.text.line_numbers import add_line_numbers

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_get_variable",
        "description": (
            "Get a persistent memory item scoped to the current project or a "
            "specified project."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to fetch.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    ),
                },
                "render_text": {
                    "type": "boolean",
                    "description": (
                        "If true and the stored value is a JSON string, return the "
                        "raw string instead of a JSON-encoded value."
                    ),
                },
                "number_lines": {
                    "type": "boolean",
                    "description": (
                        "If true, return a line-numbered view of the value. "
                        "The memory item must be a top-level JSON string."
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


def execute(args: dict, _session_data: dict | None = None) -> str:
    key = args["key"]
    project = args.get("project", os.getcwd())
    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn, project).get_value(key)
    if args.get("number_lines"):
        if not isinstance(value, str):
            return f"key {key} is not a json string"
        return add_line_numbers(value, start_line=1)
    if args.get("render_text") and isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
