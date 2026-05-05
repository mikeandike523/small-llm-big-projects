from __future__ import annotations

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
            "History holds up to 10,000 scrollback lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "terminal_id": {
                    "type": "string",
                    "description": "The terminal ID returned by open_in_terminal (6 hex digits).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["head", "tail", "screen", "all"],
                    "description": (
                        "'head': first num_lines lines (default 50). "
                        "'tail': last num_lines lines (default 50). "
                        "'screen': last 24 lines (approximate current visible screen). "
                        "'all': full output buffer."
                    ),
                },
                "num_lines": {
                    "type": "number",
                    "description": "Number of lines for head/tail mode. Ignored for screen and all.",
                },
            },
            "required": ["terminal_id", "mode"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    terminal_id = args["terminal_id"]
    mode = args["mode"]
    num_lines = args.get("num_lines")
    if num_lines is not None:
        num_lines = int(num_lines)

    get_output = sr.get("get_terminal_output")
    if get_output is None:
        return "Error: read_open_terminal is not available in this context (no terminal backend attached)."

    return get_output(terminal_id, mode, num_lines)
