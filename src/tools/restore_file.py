from __future__ import annotations

from pathlib import Path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "restore_file",
        "description": (
            "Restore a file from a snapshot taken during this session.\n\n"
            "By default restores from the latest snapshot (highest index).\n"
            "Use snapshot_index=0 to restore the original pre-session state\n"
            "(auto-captured before the first edit).\n\n"
            "Use action='list' to see all available snapshots for a file.\n"
            "Use snapshot_index to restore from a specific checkpoint."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to restore.",
                },
                "action": {
                    "type": "string",
                    "enum": ["restore", "list"],
                    "description": "restore: write snapshot content to disk (default). list: show available snapshots.",
                },
                "snapshot_index": {
                    "type": "integer",
                    "description": (
                        "Which snapshot to restore. 0 = original (auto-snapshot before first edit)."
                        " Default: latest snapshot (highest index)."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

NO_STUB = True


def dirty_effects(args: dict) -> dict:
    if args.get("action", "restore") == "restore":
        path = args.get("path")
        if path:
            return {"dirties_files": [path]}
    return {}


def needs_approval(args: dict) -> bool:
    return args.get("action", "restore") == "restore"


def execute(args: dict, session_data: dict, special_resources: dict) -> str:
    path = args["path"]
    action = args.get("action", "restore")
    session_id: str = special_resources.get("session_id", "")

    from src.tools._file_snapshot import list_snapshots, get_snapshot

    snapshots = list_snapshots(session_id, path)

    if action == "list":
        if not snapshots:
            return f"No snapshots found for: {path}"
        lines = [f"Snapshots for {path}:"]
        for s in snapshots:
            label = "(auto)" if s["snapshot_order"] == 0 else "(manual)"
            lines.append(f"  index {s['snapshot_order']}: {s['created_at']} {label}")
        return "\n".join(lines)

    if not snapshots:
        return (
            f"Error: No snapshots found for {path}. "
            "The file was not modified this session, or it was newly created "
            "(no original state exists to restore)."
        )

    # Default to the latest snapshot when no index is specified.
    if "snapshot_index" in args:
        snapshot_index = args["snapshot_index"]
    else:
        snapshot_index = snapshots[-1]["snapshot_order"]

    content = get_snapshot(session_id, path, snapshot_index)
    if content is None:
        available = ", ".join(str(s["snapshot_order"]) for s in snapshots)
        return (
            f"Error: No snapshot at index {snapshot_index} for {path}. "
            f"Available indexes: {available}"
        )

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return f"File restored from snapshot (index {snapshot_index}): {path}"
    except OSError as e:
        return f"Error writing restored content: {e}"
