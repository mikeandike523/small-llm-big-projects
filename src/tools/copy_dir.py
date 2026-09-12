from __future__ import annotations

import os
import shutil
from src.tools._path_utils import _resolve_path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "copy_dir",
        "description": "Recursively copy directory src to dst.",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {
                    "type": "string",
                    "description": "Path of the source directory. Accepts relative (resolved from cwd) or absolute paths.",
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
                        "If true (default), follow symlinks and recursively copy their targets. "
                        "If false, preserve symlinks themselves (including broken/circular links)."
                    ),
                },
                "ignore_dangling_symlinks": {
                    "type": "boolean",
                    "description": (
                        "If true, silently skip dangling (broken) symlinks when follow_symlinks is true. "
                        "If false (default), broken symlinks cause an error."
                    ),
                },
                "dirs_exist_ok": {
                    "type": "boolean",
                    "description": (
                        "If true, merge into an existing destination directory tree; ordinary file "
                        "conflicts may be overwritten. If false (default), dst must not already exist."
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
    follow_symlinks = bool(args.get("follow_symlinks", True))
    ignore_dangling_symlinks = bool(args.get("ignore_dangling_symlinks", False))
    dirs_exist_ok = bool(args.get("dirs_exist_ok", False))

    if not os.path.lexists(src):
        return f"Error: source does not exist: {src}"
    if not os.path.isdir(src):
        return f"Error: source is not a directory: {src}"

    copy_func = shutil.copy2 if preserve_metadata else shutil.copy

    try:
        result = shutil.copytree(
            src,
            dst,
            symlinks=not follow_symlinks,
            ignore_dangling_symlinks=ignore_dangling_symlinks,
            copy_function=copy_func,
            dirs_exist_ok=dirs_exist_ok,
        )
        return f"Directory copied: {src} -> {result}"
    except OSError as e:
        return f"Error: {e}"