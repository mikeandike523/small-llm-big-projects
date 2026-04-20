from __future__ import annotations

import json
import httpx

from src.utils.exceptions import ToolTimeoutError
from src.utils.docker_compose import get_service_port
from src.tools.advanced_code_interpreter import (
    DEFAULT_TIMEOUT,
    MAX_ALLOWABLE_TIMEOUT,
    _PISTON_EXECUTE_PATH,
    _get_piston_port,
    _run_piston,
)

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 1000

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "simple_code_interpreter",
        "description": (
            "Execute a Python script in a sandboxed environment. "
            "Pass the source code directly as a string and any arguments as a flat list of JSON values. "
            "Write the code as a normal executable program — include a "
            "'if __name__ == \"__main__\":' guard. "
            "Arguments arrive as sys.argv[1], sys.argv[2], etc. "
            "(strings pass through as-is; all other JSON types are JSON-serialised). "
            "On success, returns stdout as-is. "
            "On failure (non-zero exit), returns a string starting with 'FAILED:' "
            "containing the exit code, stdout, and stderr. "
            "Use this tool for most tasks. For session memory routing, custom timeout, "
            "or traceback control, use advanced_code_interpreter instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python source code to execute.",
                },
                "arg_values": {
                    "type": "array",
                    "description": (
                        "Arguments passed to the script as sys.argv[1], sys.argv[2], etc. "
                        "Each element is any JSON value: strings pass through as-is, "
                        "all other types (number, boolean, object, array, null) are JSON-serialised."
                    ),
                    "items": {},
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None) -> str:
    code = args.get("code")
    if not isinstance(code, str):
        return "Error: 'code' must be a string."

    raw_arg_values: list = args.get("arg_values") or []
    piston_args: list[str] = []
    for i, val in enumerate(raw_arg_values):
        if not isinstance(val, (str, int, float, bool, list, dict, type(None))):
            return f"Error: arg_values[{i}] is not a valid JSON value."
        piston_args.append(val if isinstance(val, str) else json.dumps(val))

    return _run_piston(
        code=code,
        piston_args=piston_args,
        timeout_val=DEFAULT_TIMEOUT,
        enable_tracebacks=True,
        target="return_value",
        target_key=None,
        memory={},
    )
