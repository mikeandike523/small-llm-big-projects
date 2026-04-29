from __future__ import annotations

from pathlib import Path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "write_text_file",
        "description": (
            "Write text content to a file on disk. "
            "Creates the file if it does not exist; overwrites it if it does.\n\n"
            "Content source — provide exactly one:\n"
            "  content: raw text string to write directly\n"
            "  session_memory_key: session memory key whose value is written to disk\n\n"
            "Use content for new files or complete rewrites where you have the full text ready.\n"
            "Use session_memory_key to complete the editing round-trip:\n"
            "  read_text_file(session_memory_key=...) -> text_editor(key=...) -> "
            "write_text_file(session_memory_key=...)\n\n"
            "Line endings are written verbatim with no EOL conversion for both modes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to write. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "content": {
                    "type": "string",
                    "description": "Raw text content to write. Mutually exclusive with session_memory_key.",
                },
                "session_memory_key": {
                    "type": "string",
                    "description": "Session memory key whose string value is written to the file. Mutually exclusive with content.",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "If true, create any missing parent directories. Default false.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval
    return needs_path_approval(args.get("path"))


def execute(args: dict, session_data: dict) -> str:
    path = args["path"]
    content: str | None = args.get("content")
    session_memory_key: str | None = args.get("session_memory_key")
    create_parents: bool = args.get("create_parents", False)

    if content is not None and session_memory_key is not None:
        return "Error: provide exactly one of 'content' or 'session_memory_key', not both."
    if content is None and session_memory_key is None:
        return "Error: one of 'content' or 'session_memory_key' is required."

    if session_memory_key is not None:
        memory = session_data.get("memory") if session_data else None
        if not isinstance(memory, dict):
            memory = {}
        value = memory.get(session_memory_key)
        if value is None:
            return f"Error: session memory key {session_memory_key!r} not found."
        if not isinstance(value, str):
            return f"Error: session memory key {session_memory_key!r} does not hold a text value (got {type(value).__name__})."
        content = value

    target = Path(path)
    try:
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return f"File written: {path} ({len(content)} chars)"
    except FileNotFoundError:
        return f"Error: parent directory does not exist: {target.parent}"
    except OSError as e:
        return f"Error: {e}"
