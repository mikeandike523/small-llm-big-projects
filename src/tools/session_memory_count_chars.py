from __future__ import annotations

LEAVE_OUT = "OMIT"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_count_chars",
        "description": "Count the total number of characters in a session memory item. Requires the stored value to be a text string.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to count characters for.",
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
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    return str(len(value))
