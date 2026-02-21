from __future__ import annotations

from src.tools._eol import EOL_CHOICES

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_normalize_eol",
        "description": (
            "Normalize all line endings in a session memory string value to a single style. "
            "The value is updated in place."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The session memory key whose value to normalize.",
                },
                "eol": {
                    "type": "string",
                    "enum": EOL_CHOICES,
                    "description": "Target line-ending style: 'lf' (\\n), 'crlf' (\\r\\n), or 'cr' (\\r).",
                },
            },
            "required": ["key", "eol"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict) -> str:
    from src.tools._memory import ensure_session_memory
    from src.tools._eol import normalize_eol

    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)
    key = args["key"]
    eol = args["eol"]

    if key not in memory:
        return f"Error: key {key!r} not found in session memory."
    value = memory[key]
    if not isinstance(value, str):
        return f"Error: session memory key {key!r} is not a string (got {type(value).__name__})."

    memory[key] = normalize_eol(value, eol)
    return f"Line endings normalized to {eol.upper()} for session memory key {key!r}."
