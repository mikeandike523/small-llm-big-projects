from __future__ import annotations

from src.utils.env_info import get_default_workspace_dir

LEAVE_OUT = "KEEP"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "get_global_workspace_dir",
        "description": (
            "Return the path to the global SLBP workspace directory (~/.slbp/workspace). "
            "Use this directory for temporary files, scratch work, one-off computations, "
            "and any output that does not belong inside the current project. "
            "Prefer this over writing scratch files into the active project directory."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(
    args: dict,
    session_data: dict | None = None,
) -> str:
    return get_default_workspace_dir()
