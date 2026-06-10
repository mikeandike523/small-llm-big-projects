from __future__ import annotations

from src.tools._memory import ensure_session_memory
from src.utils.env_info import format_environment_info

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "get_environment_info",
        "description": (
            "Return the current environment information: OS, shell, current working directory, "
            "initial working directory, user home directory, and global SLBP workspace directory. "
            "Optionally write the result to session memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "Where to send the result. "
                        "'return_value' (default) returns the environment info directly. "
                        "'session_memory' writes it to a session memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": "The session memory key to write the result to when target='session_memory'.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(
    args: dict,
    session_data: dict | None = None,
    special_resources: dict | None = None,
) -> str:
    sr = special_resources or {}
    target: str = args.get("target", "return_value")
    current_cwd = (sr.get("session_cwd") or "").replace("\\", "/")
    initial_cwd = (sr.get("initial_cwd") or "").replace("\\", "/")

    result = format_environment_info(current_cwd=current_cwd, initial_cwd=initial_cwd)

    if target == "return_value":
        return result

    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)
    memory_key: str = args["memory_key"]
    memory[memory_key] = result
    return f"Environment information written to session memory item {memory_key!r}"
