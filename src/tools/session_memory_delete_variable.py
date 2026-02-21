from __future__ import annotations

import json

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_delete_variable",
        "description": "Delete a memory value from the current session scope.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to delete.",
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
    deleted = key in memory
    if deleted:
        del memory[key]
    return json.dumps({"deleted": deleted, "key": key}, ensure_ascii=False)
