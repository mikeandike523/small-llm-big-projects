from __future__ import annotations

import os
import shutil
from src.tools._path_utils import _resolve_path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "copy_file",
        "description": "Copy a single file from src to dst.",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {
                    "type": "string",
                    "description": "Path of the source file. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "dst": {
                    "type": "string",
                    "description": "Path of the destination. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "preserve_metadata": {
                    "type": "boolean",
                    "description": (
                        "If true (default), use shutil.copy2 to preserve file contents, mode bits, "
                        "timestamps, and additional supported filesystem metadata. "
                        "If false, use shutil.copy to preserve only contents and mode bits."
                    ),
                },
                "follow_symlinks": {
                    "type": "boolean",
                    "description": (
                        "If true (default), follow the symlink chain and copy the target file. "
                        "If false, copy the symlink itself (including broken symlinks)."
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
    session_cwd = sr.get("session_cwd")
    src = _resolve_path(args["src"], session_cwd)
    dst = _resolve_path(args["dst"], session_cwd)
    preserve_metadata = bool(args.get("preserve_metadata", True))
    follow_symlinks = bool(args.get("follow_symlinks", True))

    if not os.path.lexists(src):
        return f"Error: source does not exist: {src}"

    copy_func = shutil.copy2 if preserve_metadata else shutil.copy

    try:
        copy_func(src, dst, follow_symlinks=follow_symlinks)
        return f"File copied: {src} -> {dst}"
    except OSError as e:
        return f"Error: {e}"