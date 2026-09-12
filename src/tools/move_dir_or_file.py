from __future__ import annotations

import os
import shutil
from src.tools._path_utils import _resolve_path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "move_dir_or_file",
        "description": "Move a file, directory, or symlink from src to dst.",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {
                    "type": "string",
                    "description": "Path of the source file, directory, or symlink. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "dst": {
                    "type": "string",
                    "description": "Path of the destination. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "preserve_metadata": {
                    "type": "boolean",
                    "description": (
                        "If true (default), use shutil.copy2 to preserve metadata during "
                        "cross-filesystem copy-and-delete fallback. If false, use shutil.copy. "
                        "Ignored when a simple filesystem rename is possible."
                    ),
                },
            },
            "required": ["src", "dst"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    session_cwd = sr.get("session_current_working_dir")
    src = _resolve_path(args["src"], session_cwd)
    dst = _resolve_path(args["dst"], session_cwd)
    preserve_metadata = bool(args.get("preserve_metadata", True))

    if not os.path.lexists(src):
        return f"Error: source does not exist: {src}"

    copy_func = shutil.copy2 if preserve_metadata else shutil.copy

    try:
        result = shutil.move(src, dst, copy_function=copy_func)
        return f"Moved: {src} -> {result}"
    except OSError as e:
        return f"Error: {e}"