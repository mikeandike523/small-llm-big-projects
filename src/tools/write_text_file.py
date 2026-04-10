from __future__ import annotations

from pathlib import Path

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "write_text_file",
        "description": (
            "Write text content directly to a file on disk in one step. "
            "Creates the file if it does not exist; overwrites it if it does. "
            "\n\n"
            "Use this for small files or complete rewrites where you already have "
            "the full content ready. "
            "For editing existing files, use the session memory path instead "
            "(read_text_file_to_session_memory -> session_memory_text_editor -> "
            "write_text_file_from_session_memory), which protects the original file "
            "and enables precise line-level edits."
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
                    "description": "The full text content to write to the file.",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "If true, create any missing parent directories. Default false.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval
    return needs_path_approval(args.get("path"))


def execute(args: dict, session_data: dict) -> str:
    path = args["path"]
    content = args["content"]
    create_parents: bool = args.get("create_parents", False)

    target = Path(path)

    try:
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"File written: {path} ({len(content)} chars)"
    except FileNotFoundError:
        return f"Error: parent directory does not exist: {target.parent}"
    except OSError as e:
        return f"Error: {e}"
