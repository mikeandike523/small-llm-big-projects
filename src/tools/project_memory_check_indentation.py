from __future__ import annotations

import os

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_check_indentation",
        "description": (
            "Report indentation style statistics for a string value stored in project memory. "
            "Inspects only leading whitespace on each non-blank line and reports whether "
            "indentation uses tabs, spaces, or a mix, along with the most common indent widths."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The project memory key whose value to inspect.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    ),
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, _session_data: dict | None = None) -> str:
    from src.tools._indentation import check_indentation
    from src.data import get_pool
    from src.utils.sql.kv_manager import KVManager

    key = args["key"]
    project = args.get("project", os.getcwd())

    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn, project).get_value(key)

    if value is None:
        return f"Error: key {key!r} not found in project memory."
    if not isinstance(value, str):
        return f"Error: project memory key {key!r} is not a string (got {type(value).__name__})."

    return check_indentation(value)
