from __future__ import annotations

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 300
NO_STUB = True

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_skill_file",
        "description": (
            "Read the contents of a skill file by filename. "
            "Use list_skill_files first to see available filenames."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The skill filename to read (e.g. 'coding.md').",
                },
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    filename = args.get("filename", "").strip()
    if not filename:
        return "Error: 'filename' is required."

    registry: list[dict] = session_data.get("__skill_files__") or []
    entry = next((e for e in registry if e.get("filename") == filename), None)
    if entry is None:
        available = ", ".join(e["filename"] for e in registry) if registry else "(none)"
        return (
            f"Error: Skill file {filename!r} not found. "
            f"Available filenames: {available}. "
            "Use list_skill_files to see the full list."
        )

    try:
        with open(entry["path"], encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        return f"Error: Could not read skill file {filename!r}: {e}"
