from __future__ import annotations

from pathlib import Path

from src.tools._path_utils import _resolve_path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "snapshot_file",
        "description": (
            "Save the current content of a file as a checkpoint in this session's snapshot history.\n\n"
            "Snapshots are stored per-session and can be restored with restore_file.\n"
            "Use this before making risky edits so you can recover the known-good state.\n\n"
            "The first write to any file in a session automatically creates snapshot index 0.\n"
            "Each subsequent snapshot_file call creates the next index (1, 2, ...)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to snapshot.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

NO_STUB = True


def execute(args: dict, session_data: dict, special_resources: dict) -> str:
    # Resolve relative paths against the session CWD, not the server process
    # CWD, so the snapshot key matches the file the agent actually edits.
    path = _resolve_path(args["path"], special_resources.get("session_cwd"))
    session_id: str = special_resources.get("session_id", "")

    target = Path(path)
    if not target.is_file():
        return f"Error: file not found: {path}"

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error reading file: {e}"

    try:
        from src.tools._file_snapshot import take_snapshot

        order = take_snapshot(session_id, str(target.resolve()), content)
        return f"Snapshot saved (index {order}): {path}"
    except Exception as e:
        return f"Error saving snapshot: {e}"
