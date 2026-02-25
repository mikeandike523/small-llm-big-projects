from __future__ import annotations

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 500

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_read_char_range",
        "description": (
            "Read all characters or a character range from a session memory item. "
            "Requires the stored value to be a text string. "
            "start_char is 0-based inclusive; end_char is 0-based exclusive. "
            "Omit both to read the entire value."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to read.",
                },
                "start_char": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional 0-based character index to start reading from (inclusive).",
                },
                "end_char": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional 0-based character index to stop reading at (exclusive).",
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

    start_char = args.get("start_char")
    end_char = args.get("end_char")

    if start_char is not None and start_char < 0:
        return "Error: start_char must be >= 0"
    if end_char is not None and end_char < 0:
        return "Error: end_char must be >= 0"
    if start_char is not None and end_char is not None and end_char < start_char:
        return "Error: end_char must be >= start_char"

    return value[start_char:end_char]
