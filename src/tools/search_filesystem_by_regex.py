from __future__ import annotations

import json
import os
import re
import threading

ENABLE_REDACTION = True

from src.terminal.shell_resolver import resolve_cmd as _resolve_cmd
from src.tools._subprocess import run_command
from src.tools._validate_timeout import validate_timeout
from src.utils.exceptions import ToolTimeoutError

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
TIMEOUT_HINT = "Restrict the search path or use a more specific regular expression."

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "search_filesystem_by_regex",
        "description": (
            "Search file contents under a given path using a regular expression. "
            "Powered by ripgrep — fast, cancellable, time-bounded, and .gitignore-aware. "
            "Results are grouped by file; matched substrings are highlighted in bold "
            "using ANSI escape codes.\n\n"
            "Regex restrictions (linear-time only):\n"
            "  - No backreferences (e.g. \\1)\n"
            "  - No lookahead (?=...) or (?!...)\n"
            "  - No lookbehind (?<=...) or (?<!...)\n"
            "  - No lookaround of any kind\n"
            "Standard features are allowed: character classes, alternation, "
            "quantifiers, anchors, non-capturing groups (?:...), Unicode categories."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "The regular expression to search for. Must be linear-time "
                        "(no backreferences, no lookahead/lookbehind/lookaround)."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory to search. Accepts relative (resolved from cwd) "
                        "or absolute paths. If a directory, all files are searched "
                        "recursively. Default: current working directory."
                    ),
                },
                "use_gitignore": {
                    "type": "boolean",
                    "description": (
                        "If true, respect .gitignore rules during search, including "
                        "outside Git repositories. The .git directory is excluded. "
                        "Default: true."
                    ),
                },
                "timeout": {
                    "type": "number",
                    "description": (
                        f"Search timeout in seconds. Default {DEFAULT_TIMEOUT}, "
                        f"maximum {MAX_TIMEOUT}."
                    ),
                    "minimum": 1,
                    "maximum": MAX_TIMEOUT,
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> bool:
    from src.tools._approval import ApprovalContext, is_full_auto, needs_path_approval

    if is_full_auto(special_resources):
        return False
    return needs_path_approval(
        args.get("path"), ctx=ApprovalContext.from_special_resources(special_resources)
    )


_BOLD = "\033[1m"
_RESET = "\033[0m"


def _apply_bold(line: str, pattern: str) -> str:
    """Wrap every occurrence of pattern in the line with ANSI bold codes."""
    return re.sub(pattern, lambda match: f"{_BOLD}{match.group(0)}{_RESET}", line)


def _parse_match_events(
    stdout: str, pattern: str, search_root: str, is_single_file: bool
) -> list[str]:
    rendered_by_file: dict[str, list[str]] = {}
    for raw_event in stdout.splitlines():
        try:
            event = json.loads(raw_event)
        except (json.JSONDecodeError, TypeError):
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data") or {}
        path_text = (data.get("path") or {}).get("text")
        line_text = (data.get("lines") or {}).get("text")
        line_number = data.get("line_number")
        if not isinstance(path_text, str) or not isinstance(line_text, str):
            continue
        if not isinstance(line_number, int):
            continue

        if is_single_file:
            relative_path = "."
        else:
            absolute_path = (
                path_text
                if os.path.isabs(path_text)
                else os.path.abspath(os.path.join(os.getcwd(), path_text))
            )
            relative_path = os.path.relpath(absolute_path, search_root).replace(
                "\\", "/"
            )

        content = line_text.rstrip("\r\n")
        try:
            highlighted = _apply_bold(content, pattern)
        except re.error:
            highlighted = content
        rendered_by_file.setdefault(relative_path, []).extend(
            [f"  {line_number}:", f"  {highlighted}"]
        )

    return [
        "\n".join([f"{relative_path}:", *rendered_matches])
        for relative_path, rendered_matches in rendered_by_file.items()
    ]


def execute(
    args: dict, _session_data: dict | None = None, special_resources: dict | None = None
) -> str:
    sr = special_resources or {}
    session_cwd: str | None = sr.get("session_current_working_dir")
    cancel_event: threading.Event | None = sr.get("cancel_event")
    pattern: str = args.get("pattern", "")
    raw_path: str = args.get("path", "")
    use_gitignore: bool = args.get("use_gitignore", True)
    timeout = args.get("timeout", DEFAULT_TIMEOUT)

    validate_timeout(
        "search_filesystem_by_regex", timeout, DEFAULT_TIMEOUT, MAX_TIMEOUT
    )

    display_path = raw_path or "."
    path = raw_path or session_cwd or os.getcwd()
    if not os.path.isabs(path):
        path = os.path.join(session_cwd or os.getcwd(), path)
    path = os.path.abspath(path)

    if not os.path.exists(path):
        return f"Error: path does not exist: {path!r}"

    is_single_file = os.path.isfile(path)
    command_args = [
        "--json",
        "--line-number",
        "--color",
        "never",
        "--no-config",
    ]
    if use_gitignore:
        command_args.append("--no-require-git")
    else:
        command_args.extend(["--no-ignore", "--hidden"])
    command_args.extend(["--regexp", pattern, "--", path])

    cmd = _resolve_cmd("rg", command_args)
    if isinstance(cmd, str):
        return cmd

    try:
        result = run_command(
            cmd,
            timeout=timeout,
            cancel_event=cancel_event,
            cwd=session_cwd,
        )
    except ToolTimeoutError as exc:
        raise ToolTimeoutError(
            "search_filesystem_by_regex",
            timeout,
            hint=exc.hint or TIMEOUT_HINT,
            prior_stdout=exc.prior_stdout,
            prior_stderr=exc.prior_stderr,
        ) from exc

    if result.returncode == 1:
        return f"Search path: {display_path}\n\nNo matches found."
    if not result.success:
        error = result.stderr.strip() or result.stdout.strip()
        if result.returncode == 127 or "command not found" in error.lower():
            return (
                "Error: ripgrep executable 'rg' was not found. "
                "Install ripgrep, add it to PATH, and restart SLBP."
            )
        return f"Error: ripgrep failed (exit {result.returncode}): {error}"

    output_blocks = _parse_match_events(result.stdout, pattern, path, is_single_file)
    if not output_blocks:
        return f"Search path: {display_path}\n\nNo matches found."
    return f"Search path: {display_path}\n\n" + "\n\n".join(output_blocks)
