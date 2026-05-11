from __future__ import annotations

import os

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "get_pwd",
        "description": (
            "Return the current working directory as a forward-slash-delimited path. "
            "Optionally write the result to session memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "Where to send the result. "
                        "'return_value' (default) returns the path directly. "
                        "'session_memory' writes the path to a session memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the result to. "
                        "Required when target is 'session_memory'."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None) -> str:
    from src.tools._memory import ensure_session_memory

    target: str = args.get("target", "return_value")
    cwd: str = os.getcwd().replace("\\", "/")

    if target == "return_value":
        return cwd

    memory_key: str = args["memory_key"]

    if target == "session_memory":
        if session_data is None:
            session_data = {}
        memory = ensure_session_memory(session_data)
        memory[memory_key] = cwd
        return f"Current working directory written to session memory item {memory_key!r}"

