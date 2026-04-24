from __future__ import annotations

import os

from src.utils.git_heuristic_is_binary import git_heuristic_is_binary

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 800

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file",
        "description": (
            "Read a text file's contents, either returning them directly or writing them "
            "to a session memory key.\n\n"
            "By default (no session_memory_key), returns the file contents directly. "
            "Set session_memory_key to write into session memory instead — required before "
            "editing with text_editor(key=...).\n\n"
            "Line endings: direct return normalizes to LF; session memory preserves them "
            "verbatim (CRLF stays CRLF) so the editor round-trip is lossless.\n\n"
            "For very large files, use file_line_reader instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to read. Accepts relative (resolved from cwd) or absolute paths.",
                },
                "session_memory_key": {
                    "type": "string",
                    "description": (
                        "If set, write the file contents to this session memory key "
                        "instead of returning them directly. Line endings are preserved verbatim."
                    ),
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
    session_memory_key: str | None = args.get("session_memory_key")

    if session_memory_key is not None:
        rp = os.path.realpath(path)
        if os.path.isfile(rp) and git_heuristic_is_binary(rp):
            return (
                "Error: file appears to be binary and cannot be loaded into session memory. "
                "Consider skipping, especially for code reviews or files ignored by git."
            )
        try:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                contents = fh.read()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: path is a directory: {path}"
        except UnicodeDecodeError as e:
            return f"Error: file is not valid UTF-8: {e}"
        except OSError as e:
            return f"Error: {e}"

        memory = session_data.get("memory")
        if not isinstance(memory, dict):
            memory = {}
            session_data["memory"] = memory
        memory[session_memory_key] = contents
        return f"Contents of {path!r} written to session memory key {session_memory_key!r}."

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
