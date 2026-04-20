from __future__ import annotations

LEAVE_OUT = "KEEP"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "list_skill_files",
        "description": (
            "List all available skill files (built-in and custom). "
            "Returns each skill's title and filename. "
            "Use read_skill_file(filename=...) to read the contents of a specific skill."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    registry: list[dict] = session_data.get("__skill_files__") or []
    if not registry:
        return "No skill files are available for this session."

    builtin = [e for e in registry if e.get("source") == "builtin"]
    custom = [e for e in registry if e.get("source") == "custom"]

    lines: list[str] = [f"Available skills ({len(registry)}):"]
    if builtin:
        lines.append(f"\nBuilt-in ({len(builtin)}):")
        for entry in builtin:
            lines.append(f"  {entry['filename']} -- {entry['title']}")
    if custom:
        lines.append(f"\nCustom ({len(custom)}):")
        for entry in custom:
            lines.append(f"  {entry['filename']} -- {entry['title']}")

    return "\n".join(lines)
