from __future__ import annotations

from pathlib import Path

from src.tools._path_utils import _resolve_path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "create_text_file",
        "description": "Create a new text file at the given path. Fails if the file already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to create. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "If true, create any missing parent directories. Default false.",
                },
                "initial_content": {
                    "type": "string",
                    "description": "Text to write into the file on creation. Default empty.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def dirty_effects(args: dict) -> dict:
    path = args.get("path")
    if path:
        return {"dirties_files": [path]}
    return {}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    path = args["path"]
    create_parents: bool = args.get("create_parents", False)
    initial_content: str = args.get("initial_content", "")

    # Resolve relative paths against the session CWD, not the server process
    # CWD. Without this a relative path would land in the server's working
    # directory instead of the agent's project.
    session_cwd = (special_resources or {}).get("session_cwd")
    target = Path(_resolve_path(path, session_cwd))

    try:
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return f"Error: file already exists: {path}"
        target.write_text(initial_content, encoding="utf-8")
        return f"File created: {path}"
    except FileNotFoundError:
        return f"Error: parent directory does not exist: {target.parent}"
    except OSError as e:
        return f"Error: {e}"
