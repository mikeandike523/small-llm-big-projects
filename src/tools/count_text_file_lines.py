from __future__ import annotations

import json

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "count_text_file_lines",
        "description": "Count lines in a text file efficiently by scanning for newline bytes.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description":
                    "The path of the file. It can be either relative to cwd, or absolute."
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        },
    },
}


def execute(args: dict, _session_data: dict | None = None) -> str:
    filepath = args["filepath"]
    chunk_size = 1024 * 1024

    newline_count = 0
    saw_any_bytes = False
    ends_with_newline = False

    with open(filepath, "rb") as fl:
        while True:
            chunk = fl.read(chunk_size)
            if not chunk:
                break
            saw_any_bytes = True
            newline_count += chunk.count(b"\n")
            ends_with_newline = chunk[-1] == 10

    if not saw_any_bytes:
        line_count = 0
    elif ends_with_newline:
        line_count = newline_count
    else:
        line_count = newline_count + 1

    return json.dumps({"line_count": line_count}, ensure_ascii=False)
