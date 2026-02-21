from __future__ import annotations

import json

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_set_variable",
        "description": (
            "Set a memory value in the current session scope. "
            "The value must be valid JSON (string, number, boolean, null, "
            "object, or array). To store text, pass a JSON string — "
            "e.g. \"hello world\" (quoted and escaped)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to store.",
                },
                "value": {
                    "description": (
                        "The JSON value to store. Must be a valid JSON literal "
                        "(string, number, boolean, null, object, or array). "
                        "Text must be passed as a JSON string (quoted and escaped)."
                    ),
                },
            },
            "required": ["key", "value"],
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
    memory[key] = args["value"]
    return json.dumps({"key": key}, ensure_ascii=False)
