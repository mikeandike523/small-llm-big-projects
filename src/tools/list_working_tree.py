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

def needs_approval(args: dict) -> bool:
    # If no path arg, always operates on cwd — auto-approved.
    # If path is provided, only gate if it resolves outside cwd.
    raw = args.get("path")
    if not raw:
        return False
    from src.tools._approval import _resolve, _is_under_cwd
    return not _is_under_cwd(_resolve(raw))


def execute(args: dict, _session_data={}) -> str:
    path: str | None = args.get("path")
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    if path is not None:
        resolved = os.path.abspath(path)
        cmd += ["--", resolved]
    try:
        result = run_command(cmd, timeout=DEFAULT_TIMEOUT)
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
            return _list_dir.execute(fallback_args, _session_data)
        return f"Error (exit {result.returncode}): {result.stderr.strip()}"
    return result.stdout.strip()
