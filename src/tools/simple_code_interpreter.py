from __future__ import annotations

import json
import httpx

from src.utils.exceptions import ToolTimeoutError
from src.utils.docker_compose import get_service_port

DEFAULT_TIMEOUT = 30
MAX_ALLOWABLE_TIMEOUT = 120

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 1000

_PISTON_EXECUTE_PATH = "/api/v2/execute"
_piston_port: int | None = None


def _get_piston_port() -> int:
    global _piston_port
    if _piston_port is None:
        _piston_port = get_service_port("piston", 2000)
    return _piston_port


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
            "Use this tool for most tasks. When code, arguments, or output must come from "
            "or be written to session memory keys, use session_memory_code_interpreter instead."
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
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _strip_traceback(stderr: str) -> str:
    result: list[str] = []
    in_traceback = False
    for line in stderr.splitlines():
        if line.startswith("Traceback (most recent call last):"):
            in_traceback = True
            continue
        if in_traceback:
            if line.startswith("  ") or line.startswith("\t"):
                continue
            in_traceback = False
            result.append(line)
        else:
            result.append(line)
    return "\n".join(result).strip()


def _validate_timeout(raw) -> tuple[int | None, str | None]:
    if raw is None:
        return DEFAULT_TIMEOUT, None
    if isinstance(raw, bool):
        return None, (
            f"Error: 'timeout' must be an integer, got bool. "
            f"Provide a value between 1 and {MAX_ALLOWABLE_TIMEOUT}."
        )
    if not isinstance(raw, int):
        return None, (
            f"Error: 'timeout' must be an integer, got {type(raw).__name__}. "
            f"Provide a value between 1 and {MAX_ALLOWABLE_TIMEOUT}."
        )
    if not (1 <= raw <= MAX_ALLOWABLE_TIMEOUT):
        return None, (
            f"Error: 'timeout' must be between 1 and {MAX_ALLOWABLE_TIMEOUT}, got {raw}."
        )
    return raw, None


def _run_piston(
    code: str,
    piston_args: list[str],
    timeout_val: int,
    enable_tracebacks: bool,
    target: str,
    target_key: str | None,
    memory: dict,
    tool_name: str = "simple_code_interpreter",
) -> str:
    piston_url = f"http://127.0.0.1:{_get_piston_port()}"
    payload = {
        "language": "python",
        "version": "*",
        "files": [{"name": "main.py", "content": code}],
        "stdin": "",
        "args": piston_args,
        "run_timeout": timeout_val * 1000,
        "compile_timeout": 10000,
    }

    try:
        with httpx.Client(timeout=timeout_val + 5) as client:
            resp = client.post(f"{piston_url}{_PISTON_EXECUTE_PATH}", json=payload)
    except httpx.ConnectError:
        return (
            f"Error: Could not connect to Piston at {piston_url!r}. "
            "Make sure the Piston container is running (docker compose up piston). "
            "If the Python runtime is not yet installed, run server/setup_piston.sh."
        )
    except httpx.TimeoutException:
        raise ToolTimeoutError(
            tool_name,
            timeout_val,
            hint="Increase the timeout parameter or optimise the code.",
        )
    except Exception as e:
        return f"Error: Piston request failed: {type(e).__name__}: {e}"

    if resp.status_code != 200:
        body = resp.text[:500]
        if resp.status_code in (400, 404, 422) and "language" in body.lower():
            return (
                f"Error: Piston returned HTTP {resp.status_code}. "
                "The Python runtime may not be installed. "
                "Run server/setup_piston.sh to install it. "
                f"Piston response: {body}"
            )
        return f"Error: Piston returned HTTP {resp.status_code}. Response: {body}"

    try:
        data = resp.json()
    except Exception as e:
        return f"Error: Could not parse Piston response as JSON: {e}\nRaw: {resp.text[:500]}"

    run = data.get("run", {})
    stdout: str = run.get("stdout", "")
    stderr: str = run.get("stderr", "")
    exit_code: int = run.get("code", 0)

    if exit_code != 0:
        parts = [f"FAILED: exit code {exit_code}."]
        if stderr:
            displayed_stderr = stderr if enable_tracebacks else _strip_traceback(stderr)
            if displayed_stderr:
                parts.append(f"Stderr:\n{displayed_stderr}")
        if stdout:
            parts.append(f"Stdout:\n{stdout}")
        return "\n".join(parts)

    result = stdout
    if stderr.strip():
        result = f"{stdout}\n[stderr]\n{stderr}".strip()

    if target == "session_memory":
        memory[target_key] = result
        return f"Code executed successfully. Stdout written to session memory key {target_key!r}."

    return result


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

    timeout_val, timeout_err = _validate_timeout(args.get("timeout"))
    if timeout_err:
        return timeout_err

    enable_tracebacks: bool = args.get("enable_tracebacks", True)

    return _run_piston(
        code=code,
        piston_args=piston_args,
        timeout_val=timeout_val,
        enable_tracebacks=enable_tracebacks,
        target="return_value",
        target_key=None,
        memory={},
        tool_name="simple_code_interpreter",
    )
