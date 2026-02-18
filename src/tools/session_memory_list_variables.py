from __future__ import annotations

import json

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_list_variables",
        "description": "List memory keys in the current session scope.",
        "parameters": {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Optional key prefix filter.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional maximum number of keys to return.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional pagination offset.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


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

    prefix = args.get("prefix")
    offset = int(args.get("offset", 0))
    limit = args.get("limit")
    if limit is not None:
        limit = int(limit)

    keys = sorted(memory.keys())
    if prefix is not None:
        keys = [k for k in keys if k.startswith(prefix)]
    if offset:
        keys = keys[offset:]
    if limit is not None:
        keys = keys[:limit]

    return json.dumps(keys, ensure_ascii=False)
