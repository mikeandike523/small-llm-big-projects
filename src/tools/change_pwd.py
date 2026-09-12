from __future__ import annotations

import os

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "change_pwd",
        "description": (
            "Change the current working directory to the given path. "
            "Accepts absolute or relative paths."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory to change into. Accepts relative (resolved from cwd) or absolute paths.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict, _session_data: dict | None = None, special_resources: dict | None = None) -> bool:
    from src.tools._approval import ApprovalContext, file_needs_approval

    return file_needs_approval(args, ctx=ApprovalContext.from_special_resources(special_resources))


def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    session_cwd: str | None = sr.get("session_current_working_dir")
    on_cwd_change = sr.get("on_cwd_change")
    path: str = args["path"]

    if not os.path.isabs(path):
        if not session_cwd:
            return "Error: cannot resolve relative path — session CWD is unknown."
        path = os.path.normpath(os.path.join(session_cwd, path))

    if not os.path.exists(path):
        return f"Error: path does not exist: {path}"
    if not os.path.isdir(path):
        return f"Error: path is not a directory: {path}"

    new_path = path.replace("\\", "/")
    if on_cwd_change:
        on_cwd_change(path)
    return f"Working directory changed to: {new_path}"
