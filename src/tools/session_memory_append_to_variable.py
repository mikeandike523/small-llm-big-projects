from __future__ import annotations

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_append_to_variable",
        "description": (
            "Append text to an existing session memory variable, "
            "writing the result back to the same key. The key must hold a "
            "text value (or be absent, treated as empty string)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "The session memory key to read from and write back to. "
                        "The stored value must be a text string (or absent, "
                        "treated as empty string)."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "The literal text to append.",
                },
            },
            "required": ["key", "text"],
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


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)
    key = args["key"]
    text = args["text"]
    memory[key] = _as_text(memory.get(key)) + text
    return f"Appended text to {key}"
