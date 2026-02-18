from __future__ import annotations

import json

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file",
        "description": "Read the entire contents of a text file. Encoding is utf-8.",
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

def execute(args, _session_data):
    with open(args["filepath"], "r", encoding="utf-8") as fl:
        return fl.read()