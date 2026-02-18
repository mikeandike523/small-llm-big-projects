from __future__ import annotations
from src.tools._subprocess import run_command

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "list_working_tree",
        "description": "List all tracked and untracked (non-ignored) files in the git working tree.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

def execute(args: dict) -> str:
    result = run_command(["git", "ls-files", "--cached", "--others", "--exclude-standard"])
    if not result.success:
        return f"Error (exit {result.returncode}): {result.stderr.strip()}"
    return result.stdout.strip()
