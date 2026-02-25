from __future__ import annotations

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "write_text_file_from_session_memory",
        "description": (
            "Write a session memory item to a text file. "
            "The memory value must be a text string. Encoding is utf-8. "
            "This is the inverse of read_text_file_to_session_memory and completes "
            "the in-memory text editor round-trip: "
            "read_text_file_to_session_memory → edit → write_text_file_from_session_memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_key": {
                    "type": "string",
                    "description": "The session memory key to read from. Must hold a text value.",
                },
                "filepath": {
                    "type": "string",
                    "description": "The path of the file to write. Accepts relative (resolved from cwd) or absolute paths.",
                },
            },
            "required": ["memory_key", "filepath"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval
    return needs_path_approval(args.get("filepath"))


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

    memory_key = args["memory_key"]
    filepath = args["filepath"]

    value = memory.get(memory_key)
    if value is None:
        return f"Error: key {memory_key!r} not found in session memory."
    if not isinstance(value, str):
        return f"Error: key {memory_key!r} does not hold a text value (got {type(value).__name__})."

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError as e:
        return f"Error writing file: {e}"

    return f"Wrote session memory key {memory_key!r} to {filepath}."
