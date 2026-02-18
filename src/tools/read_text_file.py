from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file",
        "description": "Read the entire contents of a text file. Encoding is utf-8.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description":
                    "The path of the file. It can be either relative to cwd, or absolute."
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "Where to send the file contents. "
                        "'return_value' (default) returns the contents directly. "
                        "'session_memory' writes the contents to a session memory key. "
                        "'project_memory' writes the contents to a project memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the file contents to. "
                        "Required when target is 'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        },
    },
}


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args, session_data):
    filepath = args["filepath"]
    target = args.get("target", "return_value")

    with open(filepath, "r", encoding="utf-8") as fl:
        contents = fl.read()

    if target == "return_value":
        return contents

    memory_key = args["memory_key"]

    if target == "session_memory":
        if session_data is None:
            session_data = {}
        memory = _ensure_session_memory(session_data)
        memory[memory_key] = contents
        return f"Contents of file {filepath} were written to session memory item {memory_key}"

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, contents)
            conn.commit()
        return f"Contents of file {filepath} were written to project memory item {memory_key}"
