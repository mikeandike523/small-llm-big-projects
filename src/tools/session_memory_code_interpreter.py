from __future__ import annotations

from src.tools.simple_code_interpreter import (
    DEFAULT_TIMEOUT,
    MAX_ALLOWABLE_TIMEOUT,
    _run_piston,
    _validate_timeout,
)

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 1000

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_code_interpreter",
        "description": (
            "Execute a Python script loaded from a session memory key, with arguments drawn from "
            "session memory keys, and output written back into a session memory key. "
            "All three — code, arguments, and return value — must be session memory keys; "
            "there is no inline code or direct return. "
            "Use this when the script was built incrementally in session memory, arguments are "
            "large blobs already stored there, or the output should feed another tool without "
            "filling the conversation context. "
            "For most tasks, use simple_code_interpreter instead — it accepts code and arguments inline "
            "and returns output directly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code_session_memory_key": {
                    "type": "string",
                    "description": "Session memory key holding the Python source code to execute.",
                },
                "arg_session_memory_keys": {
                    "type": "array",
                    "description": (
                        "Session memory keys whose text values are passed as sys.argv[1], sys.argv[2], etc. "
                        "Each key must hold a string value in session memory."
                    ),
                    "items": {"type": "string"},
                },
                "return_value_session_memory_key": {
                    "type": "string",
                    "description": "Session memory key to write the script's stdout into on success.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Timeout in seconds (1-{MAX_ALLOWABLE_TIMEOUT}, default {DEFAULT_TIMEOUT})."
                    ),
                    "minimum": 1,
                    "maximum": MAX_ALLOWABLE_TIMEOUT,
                },
                "enable_tracebacks": {
                    "type": "boolean",
                    "description": (
                        "When true (default), the full Python traceback is included in stderr on failure. "
                        "Set to false to show only the final exception line — saves context when debugging is not needed."
                    ),
                },
            },
            "required": ["code_session_memory_key", "return_value_session_memory_key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory: dict = session_data.get("memory") or {}

    code_key = args.get("code_session_memory_key")
    if not code_key:
        return "Error: 'code_session_memory_key' is required."
    code = memory.get(code_key)
    if code is None:
        return f"Error: session memory key {code_key!r} not found."
    if not isinstance(code, str):
        return f"Error: session memory key {code_key!r} does not hold a text value."

    return_key = args.get("return_value_session_memory_key")
    if not return_key:
        return "Error: 'return_value_session_memory_key' is required."

    arg_keys: list = args.get("arg_session_memory_keys") or []
    piston_args: list[str] = []
    for i, key in enumerate(arg_keys):
        if not isinstance(key, str):
            return f"Error: arg_session_memory_keys[{i}] must be a string."
        val = memory.get(key)
        if val is None:
            return f"Error: argument session memory key {key!r} not found."
        if not isinstance(val, str):
            return f"Error: argument session memory key {key!r} does not hold a text value."
        piston_args.append(val)

    timeout_val, timeout_err = _validate_timeout(args.get("timeout"))
    if timeout_err:
        return timeout_err

    enable_tracebacks: bool = args.get("enable_tracebacks", True)

    return _run_piston(
        code=code,
        piston_args=piston_args,
        timeout_val=timeout_val,
        enable_tracebacks=enable_tracebacks,
        target="session_memory",
        target_key=return_key,
        memory=memory,
        tool_name="session_memory_code_interpreter",
    )
