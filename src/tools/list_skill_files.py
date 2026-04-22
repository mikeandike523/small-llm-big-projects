from __future__ import annotations

LEAVE_OUT = "KEEP"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "list_skill_files",
        "description": (
            "List all available skill files. "
            "General skills are already loaded in the system prompt. "
            "Specialized skills must be loaded on demand with read_skill_file(filename=...)."
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

    _general_sources = {"builtin_general", "custom_general"}
    _specialized_sources = {"builtin_specialized", "custom_specialized"}

    general = [e for e in registry if e.get("source") in _general_sources]
    specialized = [e for e in registry if e.get("source") in _specialized_sources]

    lines: list[str] = [f"Available skills ({len(registry)}):"]

    if general:
        lines.append(f"\nGeneral — already loaded in system prompt ({len(general)}):")
        for entry in general:
            lines.append(f"  {entry['filename']} -- {entry['title']}")

    if specialized:
        lines.append(f"\nSpecialized — load on demand ({len(specialized)}):")
        for entry in specialized:
            lines.append(f"  {entry['filename']} -- {entry['title']}")

    return "\n".join(lines)
