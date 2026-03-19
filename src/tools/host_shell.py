from __future__ import annotations

import os
import shutil
import subprocess
import threading

from src.tools._subprocess import run_command
from src.tools._managed_process import run_command_streaming
from src.tools._autoresponse import get_applicable_rules
from src.tools._validate_timeout import validate_timeout
from src.utils.exceptions import ToolTimeoutError, ToolHangError


LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 600
STREAMS_RESULT = True

MAX_TIMEOUT = 300
DEFAULT_TIMEOUT = 120
TIMEOUT_HINT = "Consider using a dedicated tool, or running a fast command on the shell"

MAX_HANG_TIMEOUT = 20
DEFAULT_HANG_TIMEOUT = 10


DEFINITION = {
    "type": "function",
    "function": {
        "name": "host_shell",
        "description": (
            "Run a command in the host shell. "
            "Highly privileged — use dedicated tools when possible. "
            "Result is returned inline (target='return_value', default) "
            "or stored in a memory key (target='session_memory' or 'project_memory')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command name or path to executable.",
                },
                "command_args": {
                    "type": "array",
                    "description": "List of arguments to pass to the command.",
                    "items": {"type": "string"},
                },
                "timeout": {
                    "type": "number",
                    "description": (
                        f"Command timeout in seconds. "
                        f"Default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT}."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "'return_value' (default): return output inline. "
                        "'session_memory': write output to a session memory key. "
                        "'project_memory': write output to a project memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "Required when target is 'session_memory' or 'project_memory'. "
                        "The key to write the command output to."
                    ),
                },
                "use_known_autoresponse": {
                    "type": "boolean",
                    "description": (
                        "If true, automatically answer known interactive prompts "
                        "(e.g. npx install confirmations) using the built-in autoresponse "
                        "manifest. Responses are matched by command name and prompt text. "
                        "Default true."
                    ),
                },
                "hang_timeout": {
                    "type": "number",
                    "description": (
                        f"Seconds of idle output after which the process is considered hung "
                        f"(no new output and no autoresponder matched). "
                        f"Default {DEFAULT_HANG_TIMEOUT}, max {MAX_HANG_TIMEOUT}."
                    ),
                },
            },
            "required": ["command", "command_args"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return True


# ---------------------------------------------------------------------------
# Active shell output registry — used by the resume handler to emit a
# shell_output_snapshot when the browser reconnects during a running shell.
# ---------------------------------------------------------------------------

_active_outputs: dict[str, list[str]] = {}
_active_outputs_lock = threading.Lock()


def get_active_output(session_id: str) -> str | None:
    """Return the accumulated shell output for a currently-running shell, or None."""
    with _active_outputs_lock:
        parts = _active_outputs.get(session_id)
        return "".join(parts) if parts is not None else None


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    command = args["command"]
    command_args = args.get("command_args", [])
    timeout = args.get("timeout", DEFAULT_TIMEOUT)
    target = args.get("target", "return_value")
    memory_key = args.get("memory_key")
    use_known_autoresponse = args.get("use_known_autoresponse", True)
    hang_timeout = args.get("hang_timeout", DEFAULT_HANG_TIMEOUT)

    validate_timeout("host_shell", timeout, DEFAULT_TIMEOUT, MAX_TIMEOUT)
    validate_timeout("host_shell hang_timeout", hang_timeout, DEFAULT_HANG_TIMEOUT, MAX_HANG_TIMEOUT)

    if target in ("session_memory", "project_memory") and not memory_key:
        return f"Error: target={target!r} requires 'memory_key'."

    sr = special_resources or {}
    on_chunk = sr.get("on_chunk")
    on_log = sr.get("on_log")
    cancel_event: threading.Event | None = sr.get("cancel_event")
    session_id: str | None = sr.get("session_id")

    try:
        resolved = shutil.which(command)
        cmd = [resolved or command] + command_args
        if on_chunk is not None:
            autoresponses = get_applicable_rules(cmd) if use_known_autoresponse else None

            # Wrap on_chunk to track accumulated output for resume snapshots.
            if session_id:
                with _active_outputs_lock:
                    _active_outputs[session_id] = []

                original_on_chunk = on_chunk

                def _tracking_on_chunk(chunk: str, _sid: str = session_id) -> None:
                    with _active_outputs_lock:
                        parts = _active_outputs.get(_sid)
                        if parts is not None:
                            parts.append(chunk)
                    original_on_chunk(chunk)

                tracked_on_chunk = _tracking_on_chunk
            else:
                tracked_on_chunk = on_chunk

            try:
                result = run_command_streaming(
                    cmd, timeout, tracked_on_chunk,
                    autoresponses=autoresponses,
                    hang_timeout=hang_timeout,
                    on_log=on_log,
                    tool_name="host_shell",
                    timeout_hint=TIMEOUT_HINT,
                    cancel_event=cancel_event,
                )
            finally:
                if session_id:
                    with _active_outputs_lock:
                        _active_outputs.pop(session_id, None)
        else:
            result = run_command(cmd, timeout, cancel_event=cancel_event)
    except subprocess.TimeoutExpired:
        # Non-streaming path timeout (run_command); no partial output available.
        raise ToolTimeoutError("host_shell", timeout, hint=TIMEOUT_HINT)
    except (ToolTimeoutError, ToolHangError):
        raise

    output = str(result)

    if target == "return_value":
        return output

    if target == "session_memory":
        memory = session_data.get("memory")
        if not isinstance(memory, dict):
            memory = {}
            session_data["memory"] = memory
        memory[memory_key] = output
        return f"Command output written to session memory key {memory_key!r}."

    if target == "project_memory":
        from src.data import get_pool
        from src.utils.sql.kv_manager import KVManager
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, output)
            conn.commit()
        return f"Command output written to project memory key {memory_key!r}."

    return output
