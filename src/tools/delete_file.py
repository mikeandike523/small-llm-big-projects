from __future__ import annotations

import os

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "delete_file",
        "description": "Delete a file at the given path. Fails if the path does not exist or is a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to delete. Accepts relative (resolved from cwd) or absolute paths.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict) -> str:
    path = args["path"]

    if not os.path.exists(path):
        return f"Error: path does not exist: {path}"
    if os.path.isdir(path):
        return f"Error: path is a directory, not a file: {path}"

    try:
        os.remove(path)
        return f"File deleted: {path}"
    except OSError as e:
        return f"Error: {e}"
