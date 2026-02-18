from __future__ import annotations

import json
import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_delete_variable",
        "description": (
            "Delete a persistent memory item scoped to the current project or a "
            "specified project."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to delete.",
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


def execute(args: dict, _session_data: dict | None = None) -> str:
    key = args["key"]
    project = args.get("project", os.getcwd())
    pool = get_pool()
    with pool.get_connection() as conn:
        manager = KVManager(conn, project)
        deleted = manager.exists(key)
        manager.delete_value(key)
        conn.commit()
    return json.dumps({"deleted": deleted, "key": key, "project": project}, ensure_ascii=False)
