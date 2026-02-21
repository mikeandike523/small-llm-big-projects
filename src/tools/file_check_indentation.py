from __future__ import annotations

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "file_check_indentation",
        "description": (
            "Report indentation style statistics for a file on disk. "
            "Inspects only leading whitespace on each non-blank line and reports whether "
            "indentation uses tabs, spaces, or a mix, along with the most common indent widths. "
            "The file is read as UTF-8."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to inspect. Accepts relative (resolved from cwd) or absolute paths.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import file_needs_approval
    return file_needs_approval(args)


def execute(args: dict, session_data: dict) -> str:
    from src.tools._indentation import check_indentation

    path = args["path"]

    try:
        with open(path, "rb") as f:
            content = f.read().decode("utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except UnicodeDecodeError:
        return f"Error: file is not valid UTF-8: {path}"
    except OSError as e:
        return f"Error: {e}"

    return check_indentation(content)
