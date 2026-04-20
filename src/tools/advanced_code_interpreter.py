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
        "name": "advanced_code_interpreter",
        "description": (
            "Execute a Python script in a sandboxed environment. "
            "Write the code as a normal executable program — include a "
            "'if __name__ == \"__main__\":' guard. Arguments are passed as "
            "command-line strings (sys.argv[1], sys.argv[2], …). "
            "On success, returns stdout as-is. "
            "On failure (non-zero exit), returns a string starting with 'FAILED:' "
            "containing the exit code, stdout, and stderr. "
            "Use simple_code_interpreter for most tasks — this tool adds session memory "
            "routing for code/args/output, custom timeout, and traceback control."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "object",
                    "description": (
                        "The Python source code to execute. "
                        "Use source='raw' with a 'value' string for inline code, "
                        "or source='session_memory' with a 'key' to load code from session memory."
                    ),
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["raw", "session_memory"],
                        },
                        "value": {
                            "type": "string",
                            "description": "The raw Python source code (when source='raw').",
                        },
                        "key": {
                            "type": "string",
                            "description": "Session memory key holding the code (when source='session_memory').",
                        },
                    },
                    "required": ["source"],
                    "additionalProperties": False,
                },
                "args": {
                    "type": "array",
                    "description": (
                        "Command-line arguments passed to the script (sys.argv[1], sys.argv[2], …). "
                        "Each entry is an object with source='raw' and a 'value' of any JSON type "
                        "(string, number, boolean, object, array, null — converted to string for argv), "
                        "or source='session_memory' and a 'key' whose stored text is used as the argument."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "enum": ["raw", "session_memory"],
                            },
                            "value": {
                                "description": "Any JSON value used as the argument (when source='raw'). Strings are passed as-is; all other types are JSON-serialised.",
                            },
                            "key": {
                                "type": "string",
                                "description": "Session memory key whose text is used as the argument (when source='session_memory').",
                            },
                        },
                        "required": ["source"],
                        "additionalProperties": False,
                    },
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "'return_value' (default): return stdout inline. "
                        "'session_memory': write stdout to target_session_memory_key and return a confirmation."
                    ),
                },
                "target_session_memory_key": {
                    "type": "string",
                    "description": "Required when target='session_memory'. Session memory key to write stdout into.",
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


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


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


def _resolve_source_object(spec: dict, memory: dict, label: str, string_only: bool = False) -> tuple[object, str | None]:
    """Resolve a {source, value|key} object. Returns (value, error).
    When string_only=True (used for code), value must be a str.
    Otherwise (used for args), any JSON value is accepted and returned as-is.
    """
    source = spec.get("source")
    if source == "raw":
        if "value" not in spec:
            return None, f"Error: {label} has source='raw' but is missing 'value'."
        val = spec["value"]
        if string_only and not isinstance(val, str):
            return None, f"Error: {label} 'value' must be a string, got {type(val).__name__!r}."
        return val, None
    if source == "session_memory":
        key = spec.get("key")
        if not key:
            return None, f"Error: {label} has source='session_memory' but is missing 'key'."
        val = memory.get(key)
        if val is None:
            return None, f"Error: {label} session memory key {key!r} not found."
        if not isinstance(val, str):
            return None, f"Error: {label} session memory key {key!r} does not hold a text value."
        return val, None
    return None, f"Error: {label} 'source' must be 'raw' or 'session_memory', got {source!r}."


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)

    timeout_val, timeout_err = _validate_timeout(args.get("timeout"))
    if timeout_err:
        return timeout_err

    enable_tracebacks: bool = args.get("enable_tracebacks", True)

    target = args.get("target", "return_value")
    target_key: str | None = args.get("target_session_memory_key")
    if target == "session_memory" and not target_key:
        return "Error: target='session_memory' requires 'target_session_memory_key'."

    # Resolve code
    code_spec = args.get("code")
    if not isinstance(code_spec, dict):
        return "Error: 'code' must be an object with 'source' and 'value' or 'key'."
    code, code_err = _resolve_source_object(code_spec, memory, "'code'", string_only=True)
    if code_err:
        return code_err

    # Resolve args -> command-line strings
    arg_specs: list = args.get("args") or []
    piston_args: list[str] = []
    for i, spec in enumerate(arg_specs):
        if not isinstance(spec, dict):
            return f"Error: args[{i}] must be an object with 'source' and 'value' or 'key'."
        val, err = _resolve_source_object(spec, memory, f"args[{i}]")
        if err:
            return err
        # Convert non-string raw values to their JSON representation for argv
        piston_args.append(val if isinstance(val, str) else json.dumps(val))

    return _run_piston(code, piston_args, timeout_val, enable_tracebacks, target, target_key, memory)


def _run_piston(
    code: str,
    piston_args: list[str],
    timeout_val: int,
    enable_tracebacks: bool,
    target: str,
    target_key: str | None,
    memory: dict,
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
            "advanced_code_interpreter",
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
