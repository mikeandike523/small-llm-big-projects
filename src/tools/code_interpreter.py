from __future__ import annotations

import json
import os

import httpx

from src.utils.exceptions import ToolTimeoutError

DEFAULT_TIMEOUT = 30        # seconds, used when the caller omits timeout
MAX_ALLOWABLE_TIMEOUT = 120  # hard cap — never allow the LLM to set higher

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 1000

_PISTON_EXECUTE_PATH = "/api/v2/execute"

# Appended after the user's code to invoke main() with JSON-decoded args from
# stdin and print the JSON-encoded return value to stdout.
# Uses private-ish names to avoid colliding with user-defined variables.
_WRAPPER = """
import json as _slbp_json, sys as _slbp_sys
_slbp_raw = _slbp_sys.stdin.read()
_slbp_args = _slbp_json.loads(_slbp_raw) if _slbp_raw.strip() else []
_slbp_result = main(*_slbp_args)
print(_slbp_json.dumps(_slbp_result, indent=2), end="")
"""

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "code_interpreter",
        "description": (
            "Execute Python code stored in session memory. "
            "The code must define main(). "
            "Each arg is a JSON-encoded string that is decoded before being passed to main(). "
            "main()'s return value is automatically JSON-encoded. "
            "Result is returned inline (target='return_value', default) "
            "or stored in a session memory key (target='session_memory')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_memory_key_code": {
                    "type": "string",
                    "description": "Session memory key containing the Python code.",
                },
                "args": {
                    "type": "array",
                    "description": (
                        "Arguments passed to main(), in order. "
                        "Each element is either a JSON-encoded string "
                        "(e.g. '\"hello\"' for a string, '42' for a number, '[1,2]' for a list) "
                        "that is decoded before calling main(), "
                        "or {\"session_memory_key\": \"key_name\"} to read a JSON value "
                        "from session memory."
                    ),
                    "items": {
                        "oneOf": [
                            {
                                "type": "string",
                                "description": "A JSON-encoded value (decoded before passing to main()).",
                            },
                            {
                                "type": "object",
                                "description": "Read a JSON value from session memory.",
                                "properties": {
                                    "session_memory_key": {
                                        "type": "string",
                                        "description": "Session memory key whose JSON value is used as the argument.",
                                    },
                                },
                                "required": ["session_memory_key"],
                                "additionalProperties": False,
                            },
                        ],
                    },
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "'return_value' (default): return the JSON-encoded result inline. "
                        "'session_memory': write the JSON-encoded result to "
                        "target_session_memory_key and return a confirmation message."
                    ),
                },
                "target_session_memory_key": {
                    "type": "string",
                    "description": (
                        "Required when target='session_memory'. "
                        "The session memory key to write the JSON-encoded result into."
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
            },
            "required": ["session_memory_key_code"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def _validate_timeout(raw) -> tuple[int | None, str | None]:
    """Return (validated_int, error_string). One of the two will be None."""
    if raw is None:
        return DEFAULT_TIMEOUT, None
    # Booleans are a subclass of int in Python — reject them explicitly.
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
    memory = _ensure_session_memory(session_data)

    # --- timeout validation (must happen before any I/O) ---
    timeout_val, timeout_err = _validate_timeout(args.get("timeout"))
    if timeout_err:
        return timeout_err

    # --- target validation ---
    target = args.get("target", "return_value")
    target_key: str | None = args.get("target_session_memory_key")
    if target == "session_memory" and not target_key:
        return "Error: target='session_memory' requires 'target_session_memory_key'."

    # --- load code from session memory ---
    code_key: str = args["session_memory_key_code"]
    code: str | None = memory.get(code_key)
    if code is None:
        return f"Error: session memory key {code_key!r} not found."
    if not isinstance(code, str):
        return f"Error: session memory key {code_key!r} does not hold a text value."

    # --- resolve and JSON-decode args ---
    # Each resolved arg is a Python object passed directly to main().
    raw_args: list = args.get("args") or []
    resolved_args: list = []
    for i, item in enumerate(raw_args):
        if isinstance(item, str):
            # Literal JSON-encoded string — decode it.
            try:
                resolved_args.append(json.loads(item))
            except json.JSONDecodeError as e:
                return f"Error: args[{i}] is not valid JSON: {e}"
        elif isinstance(item, dict):
            # Read from session memory and JSON-decode the stored value.
            key = item.get("session_memory_key")
            if not key:
                return f"Error: args[{i}] object must have a 'session_memory_key' field."
            val = memory.get(key)
            if val is None:
                return f"Error: args[{i}] session memory key {key!r} not found."
            if not isinstance(val, str):
                return f"Error: args[{i}] session memory key {key!r} does not hold a text value."
            try:
                resolved_args.append(json.loads(val))
            except json.JSONDecodeError as e:
                return f"Error: args[{i}] session memory key {key!r} does not contain valid JSON: {e}"
        else:
            return (
                f"Error: args[{i}] must be a JSON string or a "
                f"{{'session_memory_key': ...}} object, got {type(item).__name__!r}."
            )

    # --- build the final code to send to Piston ---
    full_code = code.rstrip("\n") + "\n" + _WRAPPER

    # --- build Piston request payload ---
    # resolved_args contains Python objects; json.dumps produces the JSON array
    # that the wrapper will json.loads back into the same objects.
    piston_url = os.environ.get("PISTON_URL", "http://localhost:2000").rstrip("/")
    stdin_data = json.dumps(resolved_args)

    payload = {
        "language": "python",
        "version": "*",
        "files": [{"name": "main.py", "content": full_code}],
        "stdin": stdin_data,
        "args": [],
        "run_timeout": timeout_val * 1000,   # Piston uses milliseconds
        "compile_timeout": 10000,
    }

    # --- call Piston ---
    try:
        with httpx.Client(timeout=timeout_val + 5) as client:
            resp = client.post(
                f"{piston_url}{_PISTON_EXECUTE_PATH}",
                json=payload,
            )
    except httpx.ConnectError:
        return (
            f"Error: Could not connect to Piston at {piston_url!r}. "
            "Make sure the Piston container is running "
            "(docker compose up piston) and PISTON_URL is set correctly. "
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

    # --- parse response ---
    if resp.status_code != 200:
        body = resp.text[:500]
        if resp.status_code in (400, 404, 422) and "language" in body.lower():
            return (
                f"Error: Piston returned HTTP {resp.status_code}. "
                "The Python runtime may not be installed. "
                "Run server/setup_piston.sh to install it. "
                f"Piston response: {body}"
            )
        return (
            f"Error: Piston returned HTTP {resp.status_code}. "
            f"Response: {body}"
        )

    try:
        data = resp.json()
    except Exception as e:
        return f"Error: Could not parse Piston response as JSON: {e}\nRaw: {resp.text[:500]}"

    run = data.get("run", {})
    stdout: str = run.get("stdout", "")
    stderr: str = run.get("stderr", "")
    exit_code: int = run.get("code", 0)

    if exit_code != 0:
        parts = [f"Error: code exited with code {exit_code}."]
        if stderr:
            parts.append(f"Stderr:\n{stderr}")
        if stdout:
            parts.append(f"Stdout:\n{stdout}")
        return "\n".join(parts)

    # stdout is the JSON-encoded return value produced by the wrapper's json.dumps call.
    if stderr.strip():
        result = f"{stdout}\n[stderr]\n{stderr}".strip()
    else:
        result = stdout

    if target == "session_memory":
        memory[target_key] = result
        return f"Code executed. Result written to session memory key {target_key!r}."

    return result
