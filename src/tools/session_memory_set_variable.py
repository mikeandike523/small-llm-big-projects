from __future__ import annotations

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_set_variable",
        "description": (
            "Set a memory value in the current session scope. "
            "The value is stored as plain text. Any format is accepted — "
            "prose, JSON, TOML, CSV, code, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to store.",
                },
                "value": {
                    "type": "string",
                    "description": "The text value to store.",
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
    value = args["value"]
    if not isinstance(value, str):
        return f"Error: value must be a plain string, got {type(value).__name__}."
    memory[key] = value
    return f"Stored value at key {key!r}."
