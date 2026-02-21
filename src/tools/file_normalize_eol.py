from __future__ import annotations

from src.tools._eol import EOL_CHOICES

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "file_normalize_eol",
        "description": (
            "Normalize all line endings in a file to a single style. "
            "The file is read and written as UTF-8. "
            "Original line endings are not preserved."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to normalize. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "eol": {
                    "type": "string",
                    "enum": EOL_CHOICES,
                    "description": "Target line-ending style: 'lf' (\\n), 'crlf' (\\r\\n), or 'cr' (\\r).",
                },
            },
            "required": ["path", "eol"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict) -> str:
    from src.tools._eol import normalize_eol

    path = args["path"]
    eol = args["eol"]

    try:
        with open(path, "rb") as f:
            content = f.read().decode("utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except UnicodeDecodeError:
        return f"Error: file is not valid UTF-8: {path}"
    except OSError as e:
        return f"Error reading file: {e}"

    normalized = normalize_eol(content, eol)

    try:
        with open(path, "wb") as f:
            f.write(normalized.encode("utf-8"))
    except OSError as e:
        return f"Error writing file: {e}"

    return f"Line endings normalized to {eol.upper()} in {path}."
