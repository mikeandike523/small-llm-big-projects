from __future__ import annotations

import json
from src.utils.text.line_numbers import add_line_numbers

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_get_variable",
        "description": "Get a memory value from the current session scope.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to fetch.",
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


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)
    key = args["key"]
    value = memory.get(key)
    if args.get("number_lines"):
        if not isinstance(value, str):
            return f"key {key} is not a json string"
        return add_line_numbers(value, start_line=1)
    if args.get("render_text") and isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
