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
_PISTON_RUNTIMES_PATH = "/api/v2/runtimes"

# Appended after the user's code to invoke main() with args from stdin.
# Uses private-ish names to avoid colliding with user-defined variables.
_WRAPPER = """
import json as _slbp_json, sys as _slbp_sys
_slbp_raw = _slbp_sys.stdin.read()
_slbp_args = _slbp_json.loads(_slbp_raw) if _slbp_raw.strip() else []
_slbp_result = main(*_slbp_args)
print(str(_slbp_result), end="")
"""

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "code_interpreter",
        "description": (
            "Execute Python code stored in session memory via a sandboxed Piston engine. "
            "The code must define a function named main() — no other entry point is used. "
            "main() MUST return a plain Python str. "
            "Returning any other type (dict, list, int, etc.) will result in str() being "
            "called on it, producing Python repr output which is almost certainly not useful. "
            "To return structured data, call json.dumps() inside main() and return the string. "
            "All arguments passed to main() are strings — parse explicitly if numeric types "
            "are needed (e.g. int(x), float(x)). "
            "Other helper functions may be defined alongside main(). "
            "Do NOT include 'if __name__ == \"__main__\"' — it will not be executed. "
            "Do NOT use print() for output — only the return value of main() is captured. "
            "Requires Piston to be running (see server/docker-compose.yml) and the Python "
            "runtime installed (run server/setup_piston.sh once). "
            "Configure the Piston URL via the PISTON_URL environment variable "
            "(default: http://localhost:2000)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_memory_key_code": {
                    "type": "string",
                    "description": (
                        "Session memory key whose value is the Python code to execute. "
                        "The code must define a main() function that returns a plain str."
                    ),
                },
                "args": {
                    "type": "array",
                    "description": (
                        "Ordered list of arguments to pass to main(). "
                        "Each element is either: "
                        "(a) a plain string — passed directly as that string value, or "
                        "(b) an object {\"session_memory_key\": \"<key>\"} — the value is "
                        "loaded from session memory and passed as a string. "
                        "All args arrive in main() as strings."
                    ),
                    "items": {
                        "oneOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "session_memory_key": {
                                        "type": "string",
                                        "description": "Session memory key to read the argument value from.",
                                    },
                                },
                                "required": ["session_memory_key"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Execution timeout in seconds. "
                        f"Must be an integer between 1 and {MAX_ALLOWABLE_TIMEOUT}. "
                        f"Defaults to {DEFAULT_TIMEOUT}."
                    ),
                    "minimum": 1,
                    "maximum": MAX_ALLOWABLE_TIMEOUT,
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "Where to send the result. "
                        "'return_value' (default) returns it directly. "
                        "'session_memory' writes it to a session memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "Session memory key to write the result to. "
                        "Required when target is 'session_memory'."
                    ),
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

    # --- target / memory_key validation ---
    target: str = args.get("target", "return_value")
    memory_key: str | None = args.get("memory_key")
    if target == "session_memory" and not memory_key:
        return "Error: 'memory_key' is required when target is 'session_memory'."

    # --- load code from session memory ---
    code_key: str = args["session_memory_key_code"]
    code: str | None = memory.get(code_key)
    if code is None:
        return f"Error: session memory key {code_key!r} not found."
    if not isinstance(code, str):
        return f"Error: session memory key {code_key!r} does not hold a text value."

    # --- resolve args list ---
    raw_args: list = args.get("args") or []
    resolved_args: list[str] = []
    for i, item in enumerate(raw_args):
        if isinstance(item, str):
            resolved_args.append(item)
        elif isinstance(item, dict):
            sk = item.get("session_memory_key")
            if not sk:
                return (
                    f"Error: args[{i}] is an object but is missing 'session_memory_key'."
                )
            val = memory.get(sk)
            if val is None:
                return f"Error: args[{i}] references session memory key {sk!r} which was not found."
            resolved_args.append(val if isinstance(val, str) else str(val))
        else:
            return (
                f"Error: args[{i}] has unsupported type {type(item).__name__!r}. "
                "Each element must be a string or an object with 'session_memory_key'."
            )

    # --- build the final code to send to Piston ---
    full_code = code.rstrip("\n") + "\n" + _WRAPPER

    # --- build Piston request payload ---
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
        # Common cause: Python runtime not installed in Piston.
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
        result = "\n".join(parts)
    elif stderr:
        # Non-zero exit already handled above; non-empty stderr with exit 0
        # means warnings/deprecations — include but don't treat as failure.
        result = stdout
        if stderr.strip():
            result = f"{stdout}\n[stderr]\n{stderr}".strip()
    else:
        result = stdout

    if target == "return_value":
        return result

    # target == "session_memory"
    memory[memory_key] = result
    return f"Code executed successfully. Result written to session memory key {memory_key!r}."
