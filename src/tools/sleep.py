from __future__ import annotations

from src.tools._cancellation import get_cancel_event, wait_or_cancel

MAX_SLEEP_SECONDS = 300

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "sleep",
        "description": (
            "Wait for a number of seconds, then continue. Use this instead of a shell "
            "sleep command, for example before retrying a file that is under an "
            "advisory lock. The Stop button ends the wait immediately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": MAX_SLEEP_SECONDS,
                    "description": (
                        f"How long to wait, at most {MAX_SLEEP_SECONDS} seconds."
                    ),
                },
            },
            "required": ["seconds"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> bool:
    return False


def execute(
    args: dict, session_data: dict, special_resources: dict | None = None
) -> str:
    seconds = args["seconds"]
    wait_or_cancel("sleep", get_cancel_event(special_resources), seconds)
    return f"Waited {seconds} seconds."
