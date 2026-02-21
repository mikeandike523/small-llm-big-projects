from __future__ import annotations

import os
import subprocess

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": (
            "Apply a unified diff patch to the working tree using git apply. "
            "The patch must be fully valid: context lines must match exactly and "
            "the patch must be unambiguous. On failure the full error detail is "
            "returned so the patch can be corrected and retried."
            "Note: DO NOT ADD ***begin patch*** or any special delimters. Emit ONLY the patch text. "
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": (
                        "The unified diff patch text to apply. "
                        "Required unless session_memory_key is provided."
                    ),
                },
                "session_memory_key": {
                    "type": "string",
                    "description": (
                        "If provided, load the patch text from this session memory key "
                        "instead of the patch argument. "
                        "The stored value must be a string."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args: dict, session_data: dict) -> str:
    session_memory_key = args.get("session_memory_key")

    if session_memory_key is not None:
        if session_data is None:
            session_data = {}
        memory = _ensure_session_memory(session_data)
        patch_data = memory.get(session_memory_key)
        if patch_data is None:
            return f"Error: no value found in session memory for key {session_memory_key!r}"
        if not isinstance(patch_data, str):
            return (
                f"Error: session memory key {session_memory_key!r} contains a non-string value "
                f"({type(patch_data).__name__}); patch must be a string."
            )
    else:
        patch_data = args.get("patch")
        if not patch_data:
            return "Error: either 'patch' or 'session_memory_key' must be provided."

    result = subprocess.run(
        ["git", "apply"],
        input=patch_data,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip() or "No error detail available.")
        return f"Patch apply failed:\n{detail}"

    return "Patch applied successfully."
