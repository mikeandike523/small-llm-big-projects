from __future__ import annotations

from src.terminal.shell_resolver import resolve_cmd


DEFINITION = {
    "type": "function",
    "function": {
        "name": "open_in_terminal",
        "description": (
            "Launch a command in a new tab of the user's in-browser terminal panel. "
            "Returns immediately -- the process runs live in the terminal so the user "
            "can observe output, interact with it, and experiment with it directly. "
            "Use this tool whenever you want to present an interactive application to "
            "the user: local web servers, REPLs (Python, Node, etc.), interactive CLIs, "
            "demos, test runners with live output, or any program that benefits from "
            "real-time user interaction. "
            "The terminal panel is opened and the new tab is focused automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Command name or path to executable. "
                        "If resolvable via PATH, executed directly; "
                        "otherwise wrapped in the platform login shell."
                    ),
                },
                "command_args": {
                    "type": "array",
                    "description": "List of arguments to pass to the command.",
                    "items": {"type": "string"},
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Optional label for the terminal tab (e.g. 'dev server', 'python repl'). "
                        "Defaults to the command, truncated to 40 characters."
                    ),
                },
            },
            "required": ["command", "command_args"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    command = args["command"]
    command_args = args.get("command_args", [])
    name = args.get("name") or (command[:40] if len(command) > 40 else command)

    cmd = resolve_cmd(command, command_args)
    if isinstance(cmd, str):
        return cmd  # error from shell resolution

    create_terminal = sr.get("create_terminal")
    if create_terminal is None:
        return "Error: open_in_terminal is not available in this context (no terminal backend attached)."

    try:
        terminal_id = create_terminal(cmd, name)
    except Exception as exc:
        return f"Error: Failed to open terminal: {exc}"

    return f"Terminal opened. id={terminal_id}"
