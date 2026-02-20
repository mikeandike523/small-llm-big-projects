from __future__ import annotations

import json
import os

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_set_variable",
        "description": (
            "Set the value of a persistent memory item scoped to the current "
            "project or a specified project. Projects are identified by their "
            "filesystem paths. "
            "The value must be valid JSON (string, number, boolean, null, "
            "object, or array). To store text, pass a JSON string — "
            "e.g. \"hello world\" (quoted and escaped)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to store."
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The JSON value to store. Must be a valid JSON literal "
                        "(string, number, boolean, null, object, or array). "
                        "Text must be passed as a JSON string (quoted and escaped)."
                    )
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory."
                    )
                }
            },
            "required": ["key", "value"],
            "additionalProperties": False
        }
    }
}

def execute(args: dict, _session_data: dict | None = None) -> str:
    key = args["key"]
    value = args["value"]
    project = args.get("project", os.getcwd())
    pool = get_pool()
    with pool.get_connection() as conn:
        KVManager(conn, project).set_value(key, value)
        conn.commit()
    return json.dumps({"key": key, "project": project}, ensure_ascii=False)
