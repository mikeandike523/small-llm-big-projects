from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.text.line_numbers import add_line_numbers

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file",
        "description": "Read a text file (or an inclusive line range). Encoding is utf-8.",
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
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description":
                    "Optional 1-based line number to start reading from (inclusive).",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description":
                    "Optional 1-based line number to stop reading at (inclusive).",
                },
                "number_lines": {
                    "type": "boolean",
                    "description": "If true, prefix each returned line with its line number.",
                },
            },
            "required": ["filepath"],
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
    target = args.get("target", "return_value")
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    number_lines = bool(args.get("number_lines"))

    if start_line is not None and start_line < 1:
        return "Error: start_line must be >= 1"
    if end_line is not None and end_line < 1:
        return "Error: end_line must be >= 1"
    if start_line is not None and end_line is not None and end_line < start_line:
        return "Error: end_line must be >= start_line"

    effective_start_line = start_line if start_line is not None else 1

    if start_line is None and end_line is None:
        with open(filepath, "r", encoding="utf-8") as fl:
            contents = fl.read()
    else:
        selected_lines: list[str] = []

        with open(filepath, "r", encoding="utf-8") as fl:
            for line_number, line in enumerate(fl, start=1):
                if line_number < effective_start_line:
                    continue
                if end_line is not None and line_number > end_line:
                    break
                selected_lines.append(line)

        contents = "".join(selected_lines)

    if number_lines:
        contents = add_line_numbers(contents, start_line=effective_start_line)

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
