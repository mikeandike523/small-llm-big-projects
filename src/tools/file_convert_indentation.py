from __future__ import annotations

from src.tools._indentation import INDENT_TARGET_CHOICES, DEFAULT_SPACES_PER_TAB

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "file_convert_indentation",
        "description": (
            "Convert the leading-whitespace indentation style of a file on disk. "
            "Only the indentation (leading whitespace) on each line is changed; "
            "line endings and all other content are preserved. "
            "The file is read and written as UTF-8."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to convert. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "to": {
                    "type": "string",
                    "enum": INDENT_TARGET_CHOICES,
                    "description": "Target indentation style: 'tabs' or 'spaces'.",
                },
                "spaces_per_tab": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        f"Number of spaces that equal one tab stop (used in both directions). "
                        f"Default: {DEFAULT_SPACES_PER_TAB}."
                    ),
                },
            },
            "required": ["path", "to"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict) -> str:
    from src.tools._indentation import convert_indentation

    path = args["path"]
    to = args["to"]
    spaces_per_tab = int(args.get("spaces_per_tab", DEFAULT_SPACES_PER_TAB))

    try:
        with open(path, "rb") as f:
            content = f.read().decode("utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except UnicodeDecodeError:
        return f"Error: file is not valid UTF-8: {path}"
    except OSError as e:
        return f"Error reading file: {e}"

    converted = convert_indentation(content, to, spaces_per_tab)

    try:
        with open(path, "wb") as f:
            f.write(converted.encode("utf-8"))
    except OSError as e:
        return f"Error writing file: {e}"

    return f"Indentation converted to {to} (spaces_per_tab={spaces_per_tab}) in {path}."
