from __future__ import annotations


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
                "command_line": {
                    "type": "string",
                    "description": (
                        "The shell command line to run. "
                        "Executed via 'bash -lc' (or platform equivalent) inside a PTY "
                        "so the full PATH and shell environment are available."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Optional label for the terminal tab (e.g. 'dev server', 'python repl'). "
                        "Defaults to the command line, truncated to 40 characters."
                    ),
                },
            },
            "required": ["command_line"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    sr = special_resources or {}
    command_line = args["command_line"]
    name = args.get("name") or (command_line[:40] if len(command_line) > 40 else command_line)

    create_terminal = sr.get("create_terminal")
    if create_terminal is None:
        return "Error: open_in_terminal is not available in this context (no terminal backend attached)."

    try:
        create_terminal(command_line, name)
    except Exception as exc:
        return f"Error: Failed to open terminal: {exc}"

    return "Command successfully opened in terminal."
