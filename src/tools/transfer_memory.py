from __future__ import annotations

import copy
import os

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "transfer_memory",
        "description": (
            "Copy or move a memory item between session memory and project memory (in either direction). "
            "Source and destination can be the same scope (session→session or project→project) "
            "or different scopes (session→project or project→session)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["session", "project"],
                    "description": "Memory scope to read from.",
                },
                "source_key": {
                    "type": "string",
                    "description": "The key to read from the source scope.",
                },
                "dest": {
                    "type": "string",
                    "enum": ["session", "project"],
                    "description": "Memory scope to write to.",
                },
                "dest_key": {
                    "type": "string",
                    "description": (
                        "The key to write to in the destination scope. "
                        "Defaults to source_key if omitted."
                    ),
                },
                "move": {
                    "type": "boolean",
                    "description": (
                        "If true, delete the value from the source scope after writing to the destination. "
                        "Default: false (copy semantics)."
                    ),
                },
                "force_overwrite": {
                    "type": "boolean",
                    "description": (
                        "If true, overwrite the destination key if it already exists. "
                        "Default: false (error if destination key exists)."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the current working directory. "
                        "Used for any project-scoped read or write in this operation."
                    ),
                },
            },
            "required": ["source", "source_key", "dest"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _ensure_session_memory(session_data: dict) -> dict:
    from src.tools._memory import ensure_session_memory
    return ensure_session_memory(session_data)


def execute(args: dict, session_data: dict) -> str:
    from src.data import get_pool
    from src.utils.sql.kv_manager import KVManager

    source = args["source"]
    source_key = args["source_key"]
    dest = args["dest"]
    dest_key = args.get("dest_key") or source_key
    move = bool(args.get("move", False))
    force_overwrite = bool(args.get("force_overwrite", False))
    project = args.get("project", os.getcwd())

    if session_data is None:
        session_data = {}

    # ------------------------------------------------------------------
    # Read from source
    # ------------------------------------------------------------------
    if source == "session":
        memory = _ensure_session_memory(session_data)
        if source_key not in memory:
            return f"Error: key {source_key!r} not found in session memory."
        value = copy.deepcopy(memory[source_key])

    else:  # source == "project"
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn, project)
            if not kv.exists(source_key):
                return f"Error: key {source_key!r} not found in project memory."
            value = kv.get_value(source_key)

    # ------------------------------------------------------------------
    # Check destination for existing key (when not force_overwriting)
    # ------------------------------------------------------------------
    if not force_overwrite:
        if dest == "session":
            dest_memory = _ensure_session_memory(session_data)
            if dest_key in dest_memory:
                return (
                    f"Error: key {dest_key!r} already exists in session memory. "
                    "Use force_overwrite=true to overwrite."
                )
        else:  # dest == "project"
            pool = get_pool()
            with pool.get_connection() as conn:
                if KVManager(conn, project).exists(dest_key):
                    return (
                        f"Error: key {dest_key!r} already exists in project memory. "
                        "Use force_overwrite=true to overwrite."
                    )

    # ------------------------------------------------------------------
    # Write to destination
    # ------------------------------------------------------------------
    if dest == "session":
        dest_memory = _ensure_session_memory(session_data)
        dest_memory[dest_key] = value
    else:  # dest == "project"
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(dest_key, value)
            conn.commit()

    # ------------------------------------------------------------------
    # Delete from source if moving
    # ------------------------------------------------------------------
    if move:
        if source == "session":
            memory = _ensure_session_memory(session_data)
            memory.pop(source_key, None)
        else:  # source == "project"
            pool = get_pool()
            with pool.get_connection() as conn:
                KVManager(conn, project).delete_value(source_key)
                conn.commit()

    action = "Moved" if move else "Copied"
    return f"{action} {source} memory key {source_key!r} to {dest} memory key {dest_key!r}."
