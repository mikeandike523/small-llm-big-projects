from __future__ import annotations

import json
import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_list_variables",
        "description": (
            "List persistent memory keys scoped to the current project or a "
            "specified project."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
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


def execute(args: dict, _session_data: dict | None = None) -> str:
    project = args.get("project", os.getcwd())
    prefix = args.get("prefix")
    limit = args.get("limit")
    offset = int(args.get("offset", 0))
    if limit is not None:
        limit = int(limit)

    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn, project).list_keys(
            prefix=prefix,
            limit=limit,
            offset=offset,
        )
    return json.dumps(keys, ensure_ascii=False)
