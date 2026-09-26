from __future__ import annotations

from pathlib import Path

from src.tools._path_utils import _resolve_path
from src.tools._cancellation import get_cancel_event
from src.tools._cancellable_io import remove_tree_cancellable

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
        return needs_path_approval(
            args.get("path"),
            ctx=ApprovalContext.from_special_resources(special_resources),
        )
    return True


def execute(
    args: dict, session_data: dict, special_resources: dict | None = None
) -> str:
    # Resolve relative paths against the session CWD, not the server process
    # CWD — critical here since this is a destructive (rmtree) operation.
    sr = special_resources or {}
    session_cwd = sr.get("session_current_working_dir")
    cancel_event = get_cancel_event(sr)
    path = _resolve_path(args["path"], session_cwd)
    recursive = bool(args.get("recursive", False))

    target = Path(path)

    if not target.exists():
        return f"Error: path does not exist: {path}"
    if not target.is_dir():
        return f"Error: path is not a directory: {path}"

    try:
        if recursive:
            remove_tree_cancellable(
                path,
                tool_name="remove_dir",
                cancel_event=cancel_event,
            )
        else:
            target.rmdir()
        return f"Directory removed: {path}"
    except OSError as e:
        return f"Error: {e}"
