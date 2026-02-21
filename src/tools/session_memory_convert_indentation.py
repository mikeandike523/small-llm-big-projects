from __future__ import annotations

from src.tools._indentation import INDENT_TARGET_CHOICES, DEFAULT_SPACES_PER_TAB

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_convert_indentation",
        "description": (
            "Convert the leading-whitespace indentation style of a session memory string value. "
            "Only the indentation (leading whitespace) on each line is changed; "
            "line endings and all other content are preserved. "
            "The value is updated in place."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The session memory key whose value to convert.",
                },
                "to": {
                    "type": "string",
                    "enum": INDENT_TARGET_CHOICES,
                    "description": "Target indentation style: 'tabs' or 'spaces'.",
                },
                "spaces_per_tab": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        f"Number of spaces that equal one tab stop (used in both directions). "
                        f"Default: {DEFAULT_SPACES_PER_TAB}."
                    ),
                },
            },
            "required": ["key", "to"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict) -> str:
    from src.tools._memory import ensure_session_memory
    from src.tools._indentation import convert_indentation

    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)
    key = args["key"]
    to = args["to"]
    spaces_per_tab = int(args.get("spaces_per_tab", DEFAULT_SPACES_PER_TAB))

    if key not in memory:
        return f"Error: key {key!r} not found in session memory."
    value = memory[key]
    if not isinstance(value, str):
        return f"Error: session memory key {key!r} is not a string (got {type(value).__name__})."

    memory[key] = convert_indentation(value, to, spaces_per_tab)
    return f"Indentation converted to {to} (spaces_per_tab={spaces_per_tab}) for session memory key {key!r}."
