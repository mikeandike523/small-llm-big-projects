from __future__ import annotations

from src.terminal.shell_resolver import resolve_shell_cmd, ShellNotFoundError

DEFINITION = {
    "type": "function",
    "function": {
        "name": "open_in_terminal",
        "description": (
            "Launch a command line in a new tab of the user's in-browser terminal panel. "
            "Returns immediately -- the process runs live in the terminal so the user "
            "can observe output, interact with it, and experiment with it directly. "
            "Use this tool whenever you want to present an interactive application to "
            "the user: local web servers, REPLs (Python, Node, etc.), interactive CLIs, "
            "demos, test runners with live output, or any program that benefits from "
            "real-time user interaction. "
            "The terminal panel is opened and the new tab is focused automatically.\n\n"
            "cmdline is run exactly as if typed at an interactive prompt: it is passed "
            "to a login shell (bash -lc on Linux/macOS, Git Bash -lc on Windows) inside "
            "a real TTY, so shell syntax (&&, |, quoting, env vars, etc.) works as "
            "expected. Because it runs under a shell rather than being exec'd directly, "
            "Ctrl+C in the terminal interrupts the running foreground command and drops "
            "back to the shell prompt, rather than closing the tab."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cmdline": {
                    "type": "string",
                    "description": (
                        "The full command line to run, e.g. 'python snake.py' or "
                        "'npm run dev -- --port 3000'."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Optional label for the terminal tab (e.g. 'dev server', 'python repl'). "
                        "Defaults to cmdline, truncated to 40 characters."
                    ),
                },
            },
            "required": ["cmdline"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


def execute(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> str:
    sr = special_resources or {}
    cmdline = args["cmdline"]
    name = args.get("name") or (cmdline[:40] if len(cmdline) > 40 else cmdline)

    # Client-requested behavior: unlike host_shell (which execs a directly-resolvable
    # command as-is for predictability), this tool always runs inside a login shell so
    # the terminal tab behaves like a real interactive terminal (PuTTY/ssh) -- Ctrl+C
    # interrupts the foreground command instead of tearing down the whole session.
    try:
        cmd = resolve_shell_cmd(cmdline)
    except ShellNotFoundError as exc:
        return f"Error: {exc}"

    create_terminal = sr.get("create_terminal")
    if create_terminal is None:
        return "Error: open_in_terminal is not available in this context (no terminal backend attached)."

    try:
        terminal_id = create_terminal(cmd, name)
    except Exception as exc:
        return f"Error: Failed to open terminal: {exc}"

    return f"Terminal opened. id={terminal_id}"
