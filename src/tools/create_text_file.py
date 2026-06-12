from __future__ import annotations

from pathlib import Path

from src.tools._path_utils import _resolve_path
from src.tools._auto_eol import maybe_apply_auto_eol

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
    sr = special_resources or {}
    session_cwd = sr.get("session_cwd")
    target = Path(_resolve_path(path, session_cwd))

    # Auto-EOL: normalize line endings of the new file based on the session's
    # INITIAL cwd (gated by the system.create_file_auto_eol param).
    initial_content, eol_note = maybe_apply_auto_eol(
        initial_content,
        sr.get("create_file_auto_eol"),
        sr.get("initial_cwd"),
    )

    try:
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return f"Error: file already exists: {path}"
        # newline="" prevents Python from rewriting the EOL style we just applied.
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(initial_content)
        msg = f"File created: {path}"
        if eol_note:
            msg += f" ({eol_note})"
        return msg
    except FileNotFoundError:
        return f"Error: parent directory does not exist: {target.parent}"
    except OSError as e:
        return f"Error: {e}"
