from __future__ import annotations

import os

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory_copy_rename",
        "description": (
            "Copy or rename a project memory item within the same project scope. "
            "In copy mode (default) the source key is preserved. "
            "In rename mode the source key is deleted after the value is written to the destination."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_key": {
                    "type": "string",
                    "description": "The project memory key to copy or rename.",
                },
                "dest_key": {
                    "type": "string",
                    "description": "The destination project memory key.",
                },
                "rename": {
                    "type": "boolean",
                    "description": (
                        "If true, delete source_key after writing to dest_key (move semantics). "
                        "Default: false (copy semantics)."
                    ),
                },
                "force_overwrite": {
                    "type": "boolean",
                    "description": (
                        "If true, overwrite dest_key if it already exists. "
                        "Default: false (error if dest_key exists)."
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
            "required": ["source_key", "dest_key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, _session_data: dict | None = None) -> str:
    from src.data import get_pool
    from src.utils.sql.kv_manager import KVManager

    source_key = args["source_key"]
    dest_key = args["dest_key"]
    rename = bool(args.get("rename", False))
    force_overwrite = bool(args.get("force_overwrite", False))
    project = args.get("project", os.getcwd())

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn, project)

        if not kv.exists(source_key):
            return f"Error: source key {source_key!r} not found in project memory."
        if not force_overwrite and kv.exists(dest_key):
            return (
                f"Error: destination key {dest_key!r} already exists in project memory. "
                "Use force_overwrite=true to overwrite."
            )

        value = kv.get_value(source_key)
        kv.set_value(dest_key, value)

        if rename:
            kv.delete_value(source_key)

        conn.commit()

    if rename:
        return f"Renamed project memory key {source_key!r} to {dest_key!r}."
    return f"Copied project memory key {source_key!r} to {dest_key!r}."
