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
            "History holds up to 10,000 scrollback lines.\n\n"
            "terminal_id: pass the exact id returned by open_in_terminal, or the special value "
            "'last_opened' to automatically use the most recent terminal opened by a tool call. "
            "WARNING: if the output looks unrelated to the current task, 'last_opened' may be "
            "pointing to a terminal from an earlier part of the conversation — review recent "
            "tool call results for the correct terminal id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "terminal_id": {
                    "type": "string",
                    "description": (
                        "The terminal ID returned by open_in_terminal (6 hex digits), "
                        "or 'last_opened' to resolve to the most recent tool-opened terminal "
                        "in this session. Omitting this field is an error."
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
    terminal_id = args.get("terminal_id", "")
    mode = args["mode"]
    num_lines = args.get("num_lines")
    if num_lines is not None:
        num_lines = int(num_lines)

    if not terminal_id:
        return "Error: terminal_id is required. Pass a terminal id from open_in_terminal, or 'last_opened'."

    if terminal_id == "last_opened":
        resolved = (session_data or {}).get("__last_opened_terminal_id__")
        if not resolved:
            return (
                "Error: no terminal has been opened by a tool call in this session yet. "
                "Use open_in_terminal first, then read with its returned id or 'last_opened'."
            )
        terminal_id = resolved

    get_output = sr.get("get_terminal_output")
    if get_output is None:
        return "Error: read_open_terminal is not available in this context (no terminal backend attached)."

    return get_output(terminal_id, mode, num_lines)
