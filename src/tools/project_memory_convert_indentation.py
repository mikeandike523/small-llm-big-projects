from __future__ import annotations

import os

from src.tools._indentation import INDENT_TARGET_CHOICES, DEFAULT_SPACES_PER_TAB

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_convert_indentation",
        "description": (
            "Convert the leading-whitespace indentation style of a project memory string value. "
            "Only the indentation (leading whitespace) on each line is changed; "
            "line endings and all other content are preserved. "
            "The value is updated in place."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The project memory key whose value to convert.",
                },
                "to": {
                    "type": "string",
                    "enum": INDENT_TARGET_CHOICES,
                    "description": "Target indentation style: 'tabs' or 'spaces'.",
                },
                "spaces_per_tab": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        f"Number of spaces that equal one tab stop (used in both directions). "
                        f"Default: {DEFAULT_SPACES_PER_TAB}."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    ),
                },
            },
            "required": ["key", "to"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, _session_data: dict | None = None) -> str:
    from src.tools._indentation import convert_indentation
    from src.data import get_pool
    from src.utils.sql.kv_manager import KVManager

    key = args["key"]
    to = args["to"]
    spaces_per_tab = int(args.get("spaces_per_tab", DEFAULT_SPACES_PER_TAB))
    project = args.get("project", os.getcwd())

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn, project)
        value = kv.get_value(key)

        if value is None:
            return f"Error: key {key!r} not found in project memory."
        if not isinstance(value, str):
            return f"Error: project memory key {key!r} is not a string (got {type(value).__name__})."

        kv.set_value(key, convert_indentation(value, to, spaces_per_tab))
        conn.commit()

    return f"Indentation converted to {to} (spaces_per_tab={spaces_per_tab}) for project memory key {key!r}."
