from __future__ import annotations

from dataclasses import dataclass
import json
import shlex

from src.tools import execute_tool


@dataclass(frozen=True)
class SlashCommandResult:
    handled: bool
    output: str = ""


_VALID_SCOPES = {"session-memory", "project-memory"}
_VALID_ACTIONS = {"list-items", "set-item", "delete-item"}


def _usage(scope: str) -> str:
    return "\n".join(
        [
            f"Usage for /{scope}:",
            f"  /{scope} list-items",
            f"  /{scope} set-item <key> <value>",
            f"  /{scope} delete-item <key>",
        ]
    )


def _format_tool_result(tool_result: str) -> str:
    try:
        parsed = json.loads(tool_result)
    except json.JSONDecodeError:
        return tool_result
    return json.dumps(parsed, indent=2, ensure_ascii=False)


def _coerce_session_value(raw_value: str) -> object:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def _handle_memory_command(scope: str, action: str, args: list[str], session_data: dict) -> str:
    scope_key = scope.replace("-", "_")
    if action == "list-items":
        if args:
            return f"Unexpected arguments for /{scope} list-items.\n{_usage(scope)}"
        tool_result = execute_tool(f"{scope_key}_list_variables", {}, session_data)
        return _format_tool_result(tool_result)

    if action == "set-item":
        if len(args) < 2:
            return f"Missing arguments for /{scope} set-item.\n{_usage(scope)}"
        key = args[0]
        raw_value = " ".join(args[1:])
        value = _coerce_session_value(raw_value) if scope == "session-memory" else raw_value
        tool_result = execute_tool(
            f"{scope_key}_set_variable",
            {"key": key, "value": value},
            session_data,
        )
        return _format_tool_result(tool_result)

    if action == "delete-item":
        if len(args) != 1:
            return f"Invalid arguments for /{scope} delete-item.\n{_usage(scope)}"
        tool_result = execute_tool(
            f"{scope_key}_delete_variable",
            {"key": args[0]},
            session_data,
        )
        return _format_tool_result(tool_result)

    return f"Unknown action '{action}' for /{scope}.\n{_usage(scope)}"


def try_handle_slash_command(user_input: str, session_data: dict) -> SlashCommandResult:
    stripped = user_input.strip()
    if not stripped.startswith("/"):
        return SlashCommandResult(handled=False)

    try:
        parts = shlex.split(stripped)
    except ValueError as exc:
        return SlashCommandResult(handled=True, output=f"Could not parse command: {exc}")

    if not parts:
        return SlashCommandResult(handled=True, output="Empty slash command.")

    scope = parts[0][1:]
    if scope not in _VALID_SCOPES:
        available = ", ".join(f"/{x}" for x in sorted(_VALID_SCOPES))
        return SlashCommandResult(
            handled=True,
            output=f"Unknown slash command '{parts[0]}'. Available commands: {available}",
        )

    if len(parts) < 2:
        return SlashCommandResult(handled=True, output=_usage(scope))

    action = parts[1]
    if action not in _VALID_ACTIONS:
        return SlashCommandResult(
            handled=True,
            output=f"Unknown action '{action}' for /{scope}.\n{_usage(scope)}",
        )

    return SlashCommandResult(
        handled=True,
        output=_handle_memory_command(scope, action, parts[2:], session_data),
    )
