from __future__ import annotations

import os

from src.tools._eol import EOL_CHOICES

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_normalize_eol",
        "description": (
            "Normalize all line endings in a project memory string value to a single style. "
            "The value is updated in place."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The project memory key whose value to normalize.",
                },
                "eol": {
                    "type": "string",
                    "enum": EOL_CHOICES,
                    "description": "Target line-ending style: 'lf' (\\n), 'crlf' (\\r\\n), or 'cr' (\\r).",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    ),
                },
            },
            "required": ["key", "eol"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, _session_data: dict | None = None) -> str:
    from src.tools._eol import normalize_eol
    from src.data import get_pool
    from src.utils.sql.kv_manager import KVManager

    key = args["key"]
    eol = args["eol"]
    project = args.get("project", os.getcwd())

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn, project)
        value = kv.get_value(key)

        if value is None:
            return f"Error: key {key!r} not found in project memory."
        if not isinstance(value, str):
            return f"Error: project memory key {key!r} is not a string (got {type(value).__name__})."

        kv.set_value(key, normalize_eol(value, eol))
        conn.commit()

    return f"Line endings normalized to {eol.upper()} for project memory key {key!r}."
