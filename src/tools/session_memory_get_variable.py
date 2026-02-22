from __future__ import annotations

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
                "number_lines": {
                    "type": "boolean",
                    "description": (
                        "If true, return a line-numbered view of the value. "
                        "The memory item must hold a text value."
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
            return f"Error: key {key!r} does not hold a text value."
        return add_line_numbers(value, start_line=1)
    if value is None:
        return f"(key {key!r} not found)"
    return value if isinstance(value, str) else str(value)
