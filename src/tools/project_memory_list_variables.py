from __future__ import annotations

import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

LEAVE_OUT = "KEEP"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_list_variables",
        "description": (
            "List persistent project memory keys for the current project (or a specified one)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the pinned initial working directory (or current "
                        "working directory if pinning is disabled)."
                    ),
                },
                "prefix": {
                    "type": "string",
                    "description": "Optional key prefix filter.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional maximum number of keys to return.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional pagination offset.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _get_project(args: dict, session_data: dict) -> str:
    explicit = args.get("project")
    if explicit:
        return explicit
    pinned = (session_data or {}).get("__pinned_project__")
    if pinned:
        return pinned
    return os.getcwd()


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    project = _get_project(args, session_data)
    prefix = args.get("prefix")
    offset = int(args.get("offset", 0))
    limit = args.get("limit")
    if limit is not None:
        limit = int(limit)

    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn).list_keys(
            project=project,
            prefix=prefix,
            limit=limit,
            offset=offset,
        )

    if not keys:
        return "(no keys found)"
    return "\n".join(keys)
