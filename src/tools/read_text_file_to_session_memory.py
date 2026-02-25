from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file_to_session_memory",
        "description": "Read an entire text file into session memory. Encoding is utf-8.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description":
                    "The path of the file. It can be either relative to cwd, or absolute."
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the file contents to. "
                        "Required when target is 'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": ["filepath","memory_key"],
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


def execute(args, session_data):
    filepath = args["filepath"]

    with open(filepath, "r", encoding="utf-8") as fl:
        contents = fl.read()

    memory_key = args["memory_key"]

    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)
    memory[memory_key] = contents
    return f"Contents of file {filepath} were written to session memory item {memory_key}"
