from __future__ import annotations
import json

NO_STUB = True

DEFINITION = {
    "type": "function",
    "function": {
        "name": "check_terminal_state",
        "description": (
            "Return a JSON array describing all open terminal tabs in this session. "
            "Each entry includes the terminal's ID, name, starting command, who opened it "
            "(agent or user), a special_status field if it matches a known sentinel "
            "('agent_last_opened', 'user_last_opened', 'active', 'last_asked'), and optionally "
            "the last N lines of output. "
            "Use this before read_open_terminal when you are unsure which terminal to target, "
            "or to survey all running terminals at once."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lines": {
                    "type": "number",
                    "description": (
                        "Number of tail lines to include per terminal (default 10, min 0, max 100). "
                        "Pass 0 to omit terminal output from the response entirely."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    lines = args.get("lines", 10)
    try:
        lines = int(lines)
    except (TypeError, ValueError):
        lines = 10
    lines = max(0, min(100, lines))

    get_state = sr.get("get_terminals_state")
    if get_state is None:
        return "Error: check_terminal_state is not available in this context (no terminal backend attached)."

    entries = get_state(lines)
    return json.dumps(entries, indent=2)
