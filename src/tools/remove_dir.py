from __future__ import annotations

import shutil
from pathlib import Path

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "remove_dir",
        "description": "Remove a directory at the given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the directory to remove. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": (
                        "If true, remove the directory and all its contents recursively "
                        "(equivalent to rm -rf). If false (default), the directory must be empty."
                    ),
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
    recursive = bool(args.get("recursive", False))

    target = Path(path)

    if not target.exists():
        return f"Error: path does not exist: {path}"
    if not target.is_dir():
        return f"Error: path is not a directory: {path}"

    try:
        if recursive:
            shutil.rmtree(path)
        else:
            target.rmdir()
        return f"Directory removed: {path}"
    except OSError as e:
        return f"Error: {e}"
