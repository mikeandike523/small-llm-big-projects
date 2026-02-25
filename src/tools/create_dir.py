from __future__ import annotations

from pathlib import Path

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "create_dir",
        "description": "Create a directory at the given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the directory to create. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": (
                        "If true, create all missing parent directories as needed "
                        "(equivalent to mkdir -p). Default: false."
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
    create_parents = bool(args.get("create_parents", False))

    try:
        Path(path).mkdir(parents=create_parents, exist_ok=False)
        return f"Directory created: {path}"
    except FileExistsError:
        return f"Error: path already exists: {path}"
    except FileNotFoundError:
        return (
            f"Error: one or more parent directories do not exist: {path}. "
            "Use create_parents=true to create them automatically."
        )
    except OSError as e:
        return f"Error: {e}"
