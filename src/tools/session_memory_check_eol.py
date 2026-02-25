from __future__ import annotations

LEAVE_OUT = "KEEP"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_check_eol",
        "description": (
            "Report line-ending statistics for a string value stored in session memory. "
            "Returns counts of CRLF, LF, and CR line endings and whether they are uniform or mixed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The session memory key whose value to inspect.",
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict) -> str:
    from src.tools._memory import ensure_session_memory
    from src.tools._eol import check_eol

    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)
    key = args["key"]

    if key not in memory:
        return f"Error: key {key!r} not found in session memory."
    value = memory[key]
    if not isinstance(value, str):
        return f"Error: session memory key {key!r} is not a string (got {type(value).__name__})."

    return check_eol(value)
