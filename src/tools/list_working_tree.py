from __future__ import annotations
import os
import subprocess
from src.tools._subprocess import run_command

DEFAULT_TIMEOUT = 15  # seconds
TIMEOUT_HINT = None

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "list_working_tree",
        "description": (
            "List all tracked and untracked (non-ignored) files in the git working tree. "
            "When run from a subdirectory of the repo root, only files under that subdirectory are shown. "
            "Falls back to list_dir behavior (recursive, with .gitignore filtering) if not inside a git repository. "
            "Prefer this over list_dir when inside a git repository."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Optional path to restrict the listing to a subdirectory. "
                        "Accepts relative (to cwd) or absolute paths. "
                        "Defaults to the current working directory."
                    ),
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict, _session_data: dict | None = None, special_resources: dict | None = None) -> bool:
    raw = args.get("path")
    if not raw:
        return False
    from src.tools._approval import ApprovalContext, is_path_in_scope

    return not is_path_in_scope(raw, ctx=ApprovalContext.from_special_resources(special_resources))


def execute(args: dict, _session_data={}, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    session_cwd: str | None = sr.get("session_current_working_dir")
    path: str | None = args.get("path")
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    if path is not None:
        resolved = path if os.path.isabs(path) else os.path.normpath(os.path.join(session_cwd or "", path))
        cmd += ["--", resolved]
    try:
        result = run_command(cmd, timeout=DEFAULT_TIMEOUT, cwd=session_cwd)
    except subprocess.TimeoutExpired:
        from src.utils.exceptions import ToolTimeoutError

        raise ToolTimeoutError("list_working_tree", DEFAULT_TIMEOUT)
    if not result.success:
        stderr_lower = result.stderr.lower()
        if "not a git repository" in stderr_lower or result.returncode == 128:
            from src.tools import list_dir as _list_dir

            fallback_args: dict = {"use_gitignore": True, "recursive": True}
            if path is not None:
                fallback_args["path"] = path
            return _list_dir.execute(fallback_args, _session_data, special_resources)
        return f"Error (exit {result.returncode}): {result.stderr.strip()}"
    return result.stdout.strip()
