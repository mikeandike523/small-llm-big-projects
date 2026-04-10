from __future__ import annotations

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 800

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file",
        "description": (
            "Read the full contents of a small text file directly into the response. "
            "Best for small files where you want the entire content at once. "
            "For large files, use file_reader (count_lines + read_lines) to read in chunks instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to read. Accepts relative (resolved from cwd) or absolute paths.",
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

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except IsADirectoryError:
        return f"Error: path is a directory: {path}"
    except UnicodeDecodeError as e:
        return f"Error: file is not valid UTF-8: {e}"
    except OSError as e:
        return f"Error: {e}"
