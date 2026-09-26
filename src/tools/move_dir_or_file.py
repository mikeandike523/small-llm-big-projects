from __future__ import annotations

import os
import shutil
from src.tools._path_utils import _resolve_path
from src.tools._cancellation import check_cancelled, get_cancel_event
from src.tools._cancellable_io import copy_file_cancellable

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


def needs_approval(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> bool:
    from src.tools._approval import (
        ApprovalContext,
        is_auto_accept_edits,
        is_full_auto,
        needs_path_approval,
    )

    if is_full_auto(special_resources):
        return False
    if is_auto_accept_edits(special_resources):
        ctx = ApprovalContext.from_special_resources(special_resources)
        return needs_path_approval(args.get("src"), ctx=ctx) or needs_path_approval(
            args.get("dst"), ctx=ctx
        )
    return True


def execute(
    args: dict, session_data: dict, special_resources: dict | None = None
) -> str:
    sr = special_resources or {}
    cancel_event = get_cancel_event(sr)
    check_cancelled("move_dir_or_file", cancel_event)
    session_cwd = sr.get("session_current_working_dir")
    src = _resolve_path(args["src"], session_cwd)
    dst = _resolve_path(args["dst"], session_cwd)
    preserve_metadata = bool(args.get("preserve_metadata", True))

    if not os.path.lexists(src):
        return f"Error: source does not exist: {src}"

    def copy_func(source, target, *, follow_symlinks=True):
        return copy_file_cancellable(
            source,
            target,
            tool_name="move_dir_or_file",
            cancel_event=cancel_event,
            preserve_metadata=preserve_metadata,
            follow_symlinks=follow_symlinks,
        )

    try:
        result = shutil.move(src, dst, copy_function=copy_func)
        check_cancelled("move_dir_or_file", cancel_event)
        return f"Moved: {src} -> {result}"
    except OSError as e:
        return f"Error: {e}"
