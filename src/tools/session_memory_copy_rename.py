from __future__ import annotations

import copy

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_copy_rename",
        "description": (
            "Copy or rename a session memory item. "
            "In copy mode (default) the source key is preserved. "
            "In rename mode the source key is deleted after the value is written to the destination."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_key": {
                    "type": "string",
                    "description": "The session memory key to copy or rename.",
                },
                "dest_key": {
                    "type": "string",
                    "description": "The destination session memory key.",
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
            },
            "required": ["source_key", "dest_key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict) -> str:
    from src.tools._memory import ensure_session_memory

    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)

    source_key = args["source_key"]
    dest_key = args["dest_key"]
    rename = bool(args.get("rename", False))
    force_overwrite = bool(args.get("force_overwrite", False))

    if source_key not in memory:
        return f"Error: source key {source_key!r} not found in session memory."
    if dest_key in memory and not force_overwrite:
        return (
            f"Error: destination key {dest_key!r} already exists in session memory. "
            "Use force_overwrite=true to overwrite."
        )

    memory[dest_key] = copy.deepcopy(memory[source_key])

    if rename:
        del memory[source_key]
        return f"Renamed session memory key {source_key!r} to {dest_key!r}."

    return f"Copied session memory key {source_key!r} to {dest_key!r}."
