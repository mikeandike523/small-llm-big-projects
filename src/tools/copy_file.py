from __future__ import annotations

import os
from src.tools._path_utils import _resolve_path
from src.tools._cancellation import get_cancel_event
from src.tools._cancellable_io import copy_file_cancellable

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
    session_cwd = sr.get("session_current_working_dir")
    src = _resolve_path(args["src"], session_cwd)
    dst = _resolve_path(args["dst"], session_cwd)
    preserve_metadata = bool(args.get("preserve_metadata", True))
    follow_symlinks = bool(args.get("follow_symlinks", True))

    if not os.path.lexists(src):
        return f"Error: source does not exist: {src}"

    try:
        copy_file_cancellable(
            src,
            dst,
            tool_name="copy_file",
            cancel_event=cancel_event,
            preserve_metadata=preserve_metadata,
            follow_symlinks=follow_symlinks,
        )
        return f"File copied: {src} -> {dst}"
    except OSError as e:
        return f"Error: {e}"
