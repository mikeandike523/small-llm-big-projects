from __future__ import annotations

from pathlib import Path

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 200

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "create_text_file",
        "description": "Create a new text file at the given path. Fails if the file already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to create. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "If true, create any missing parent directories. Default false.",
                },
                "initial_content": {
                    "type": "string",
                    "description": "Text to write into the file on creation. Default empty.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict) -> str:
    path = args["path"]
    create_parents: bool = args.get("create_parents", False)
    initial_content: str = args.get("initial_content", "")

    target = Path(path)

    try:
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return f"Error: file already exists: {path}"
        target.write_text(initial_content, encoding="utf-8")
        return f"File created: {path}"
    except FileNotFoundError:
        return f"Error: parent directory does not exist: {target.parent}"
    except OSError as e:
        return f"Error: {e}"
