from __future__ import annotations

import shutil

LEAVE_OUT = "KEEP"

DEFINITION = {
    "type": "function",
    "function": {
        "name": "host_check_command",
        "description": "Check whether a command is available on the host PATH.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command name to look up (e.g. 'node', 'git', 'npm').",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, _session_data: dict | None = None) -> str:
    command = args["command"]
    path = shutil.which(command)
    if path:
        return f"Command found: {path}"
    return f"Command not found: {command!r}"
