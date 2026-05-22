from __future__ import annotations

from src.utils.text_truncation import truncate_long_lines as _truncate_long_lines

ALLOW_REQUEST_UNREDACTED = True

DEFINITION = {
    "type": "function",
    "function": {
        "name": "read_open_terminal",
        "description": (
            "Read buffered output from a running terminal tab opened by open_in_terminal. "
            "Useful for checking progress, capturing output, or detecting errors without "
            "interrupting the running process. "
            "Output is rendered by a full VT100 emulator (pyte) that mirrors the terminal state, "
            "including alternate-screen-buffer programs (vim, htop, etc.) and resize events. "
            "History holds up to 10,000 scrollback lines.\n\n"
            "terminal_id accepts either a literal 6-hex terminal ID or one of the sentinel values: "
            "'agent_last_opened' (last terminal opened by a tool call), "
            "'user_last_opened' (last terminal opened by the user in the UI), "
            "'active' (the terminal tab currently visible in the UI), "
            "'last_asked' (the terminal the user flagged with 'Ask about this terminal'). "
            "Use check_terminal_state first when you are unsure which terminal to target."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "terminal_id": {
                    "type": "string",
                    "description": (
                        "A 6-hex terminal ID returned by open_in_terminal, or one of the sentinels: "
                        "'agent_last_opened', 'user_last_opened', 'active', 'last_asked'. "
                        "Omitting this field is an error."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["head", "tail", "screen", "all"],
                    "description": (
                        "'head': first num_lines lines (default 50). "
                        "'tail': last num_lines lines (default 50). "
                        "'screen': current visible terminal area (accurate, including alternate-screen programs). "
                        "'all': full scrollback + visible area."
                    ),
                },
                "num_lines": {
                    "type": "number",
                    "description": "Number of lines for head/tail mode. Ignored for screen and all.",
                },
                "max_line_length": {
                    "type": "integer",
                    "description": (
                        "Truncate lines longer than this many characters in the returned output, "
                        "appending '[... N more bytes]'. "
                        "Only applies to head and tail modes — screen and all are rendered by the "
                        "VT100 emulator which already wraps at the terminal column width. "
                        "0 disables the limit. Range: 0-256. Default: 160."
                    ),
                },
            },
            "required": ["terminal_id", "mode"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> str:
    sr = special_resources or {}
    terminal_id = args.get("terminal_id", "")
    mode = args["mode"]
    num_lines = args.get("num_lines")
    max_line_length: int = max(0, min(256, args.get("max_line_length", 160)))
    if num_lines is not None:
        num_lines = int(num_lines)

    if not terminal_id:
        return (
            "Error: terminal_id is required. Pass a 6-hex terminal ID or a sentinel: "
            "'agent_last_opened', 'user_last_opened', 'active', 'last_asked'."
        )

    get_output = sr.get("get_terminal_output")
    if get_output is None:
        return "Error: read_open_terminal is not available in this context (no terminal backend attached)."

    result = get_output(terminal_id, mode, num_lines)
    if mode in ("head", "tail"):
        result = _truncate_long_lines(result, max_line_length)
    return result
