from __future__ import annotations

import os

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "change_pwd",
        "description": (
            "Change the current working directory to the given path. "
            "Accepts absolute or relative paths."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory to change into. Accepts relative (resolved from cwd) or absolute paths.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import file_needs_approval
    return file_needs_approval(args)


def execute(args: dict, session_data: dict) -> str:
    path = args["path"]

    if not os.path.exists(path):
        return f"Error: path does not exist: {path}"
    if not os.path.isdir(path):
        return f"Error: path is not a directory: {path}"

    try:
        os.chdir(path)
        return f"Working directory changed to: {os.getcwd().replace(chr(92), '/')}"
    except OSError as e:
        return f"Error: {e}"
