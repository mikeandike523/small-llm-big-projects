from __future__ import annotations

import httpx

from src.utils.exceptions import ToolTimeoutError
from src.utils.docker_compose import get_service_port

DEFAULT_TIMEOUT = 30
MAX_ALLOWABLE_TIMEOUT = 120

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
        "name": "code_interpreter",
        "description": (
            "Execute a Python script in a sandboxed environment.\n\n"
            "Code source — provide exactly one:\n"
            "  raw_code: inline Python source code as a string\n"
            "  code_session_memory_key: session memory key holding the source code\n\n"
            "Arguments — both optional, appended in order to sys.argv:\n"
            "  sys_argv: list of strings passed as sys.argv[1], sys.argv[2], ...\n"
            "  session_memory_arg_keys: session memory keys whose string values are\n"
            "    appended after any sys_argv entries\n\n"
            "Output — omit output_session_memory_key to receive stdout directly; set it\n"
            "to write stdout into a session memory key instead.\n\n"
            "Write scripts as normal executable programs with an\n"
            "'if __name__ == \"__main__\":' guard. Scripts must be non-interactive\n"
            "(no input(), getpass(), or blocking reads). On failure (non-zero exit),\n"
            "returns a string starting with 'FAILED:' with exit code, stdout, and stderr."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "raw_code": {
                    "type": "string",
                    "description": (
                        "Python source code to execute inline. "
                        "Mutually exclusive with code_session_memory_key."
                    ),
                },
                "code_session_memory_key": {
                    "type": "string",
                    "description": (
                        "Session memory key holding the Python source code. "
                        "Mutually exclusive with raw_code."
                    ),
                },
                "sys_argv": {
                    "type": "array",
                    "description": (
                        "Strings passed as sys.argv[1], sys.argv[2], etc. "
                        "The script is responsible for parsing/interpreting them."
                    ),
                    "items": {"type": "string"},
                },
                "session_memory_arg_keys": {
                    "type": "array",
                    "description": (
                        "Session memory keys whose string values are appended to sys.argv "
                        "after any sys_argv entries. Each key must hold a string value."
                    ),
                    "items": {"type": "string"},
                },
                "output_session_memory_key": {
                    "type": "string",
                    "description": (
                        "If provided, stdout is written to this session memory key on success "
                        "instead of being returned directly. Use when output is large or feeds "
                        "directly into another session memory operation."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Timeout in seconds (1-{MAX_ALLOWABLE_TIMEOUT}, "
                        f"default {DEFAULT_TIMEOUT})."
                    ),
                    "minimum": 1,
                    "maximum": MAX_ALLOWABLE_TIMEOUT,
                },
                "enable_tracebacks": {
                    "type": "boolean",
                    "description": (
                        "When true (default), the full Python traceback is included in stderr "
                        "on failure. Set to false to show only the final exception line."
                    ),
                },
            },
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


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory: dict = session_data.get("memory") or {}

    raw_code = args.get("raw_code")
    code_key = args.get("code_session_memory_key")

    if raw_code is not None and code_key is not None:
        return "Error: Provide exactly one of 'raw_code' or 'code_session_memory_key', not both."
    if raw_code is None and code_key is None:
        return "Error: One of 'raw_code' or 'code_session_memory_key' is required."

    if raw_code is not None:
        if not isinstance(raw_code, str):
            return "Error: 'raw_code' must be a string."
        code = raw_code
    else:
        code = memory.get(code_key)
        if code is None:
            return f"Error: session memory key {code_key!r} not found."
        if not isinstance(code, str):
            return f"Error: session memory key {code_key!r} does not hold a text value."

    piston_args: list[str] = []

    sys_argv: list = args.get("sys_argv") or []
    for i, val in enumerate(sys_argv):
        if not isinstance(val, str):
            return f"Error: sys_argv[{i}] must be a string, got {type(val).__name__}."
        piston_args.append(val)

    mem_arg_keys: list = args.get("session_memory_arg_keys") or []
    for i, key in enumerate(mem_arg_keys):
        if not isinstance(key, str):
            return f"Error: session_memory_arg_keys[{i}] must be a string."
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
    output_key: str | None = args.get("output_session_memory_key")

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
            "code_interpreter",
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

    if output_key:
        memory[output_key] = result
        return f"Code executed successfully. Stdout written to session memory key {output_key!r}."

    return result
