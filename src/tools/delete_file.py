from __future__ import annotations

import os
from src.tools._path_utils import _resolve_path

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


def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    path = _resolve_path(args["path"], sr.get("session_cwd"))

    if not os.path.exists(path):
        return f"Error: path does not exist: {path}"
    if os.path.isdir(path):
        return f"Error: path is a directory, not a file: {path}"

    try:
        os.remove(path)
        return f"File deleted: {path}"
    except OSError as e:
        return f"Error: {e}"
