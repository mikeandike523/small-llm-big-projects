from __future__ import annotations

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_concat",
        "description": (
            "Concatenate two session memory text values and save the result to a "
            "destination key. Both source keys must hold text values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key_a": {
                    "type": "string",
                    "description": "The first memory key to read. The stored value must be a text string.",
                },
                "key_b": {
                    "type": "string",
                    "description": "The second memory key to read. The stored value must be a text string.",
                },
                "dest_key": {
                    "type": "string",
                    "description": "The destination memory key to write.",
                },
            },
            "required": ["key_a", "key_b", "dest_key"],
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
    key_a = args["key_a"]
    key_b = args["key_b"]
    dest_key = args["dest_key"]
    value_a = _as_text(memory.get(key_a))
    value_b = _as_text(memory.get(key_b))
    memory[dest_key] = value_a + value_b
    return f"Concatted {key_a} and {key_b} and saved to {dest_key}"
