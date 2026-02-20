from __future__ import annotations
import os
from src.tools._subprocess import run_command

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "list_working_tree",
        "description": "List all tracked and untracked (non-ignored) files in the git working tree.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Optional path to restrict the listing to a subdirectory. "
                        "Accepts relative (to cwd) or absolute paths. "
                        "Defaults to the entire working tree."
                    ),
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

def execute(args: dict, _session_data={}) -> str:
    path: str | None = args.get("path")
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    if path is not None:
        resolved = os.path.abspath(path)
        cmd += ["--", resolved]
    result = run_command(cmd)
    if not result.success:
        return f"Error (exit {result.returncode}): {result.stderr.strip()}"
    return result.stdout.strip()
