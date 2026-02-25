from __future__ import annotations

from pathlib import Path

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "create_text_file",
        "description": "Create a new empty text file at the given path. Fails if the file already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to create. Accepts relative (resolved from cwd) or absolute paths.",
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

    target = Path(path)

    try:
        target.touch(exist_ok=False)
        return f"File created: {path}"
    except FileExistsError:
        return f"Error: file already exists: {path}"
    except FileNotFoundError:
        return f"Error: parent directory does not exist: {target.parent}"
    except OSError as e:
        return f"Error: {e}"
