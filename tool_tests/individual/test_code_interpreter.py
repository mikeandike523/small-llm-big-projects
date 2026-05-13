from __future__ import annotations
import json as _json
import os

import httpx

from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def _piston_available() -> bool:
    piston_url = os.environ.get("PISTON_URL", "http://localhost:2000").rstrip("/")
    try:
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{piston_url}/api/v2/runtimes")
            return resp.status_code == 200
    except Exception:
        return False


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("code_interpreter")
    mem = env.session_data["memory"]
    try:
        # --- Validation tests (no Piston needed) ---

        # Neither raw_code nor code_session_memory_key provided
        r = execute_tool("code_interpreter", {}, env.session_data)
        cl.check(
            "neither code source",
            "Returns error when neither raw_code nor code_session_memory_key is given",
            r.startswith("Error:") or "required" in r.lower() or "missing" in r.lower(),
            f"got: {r!r}",
        )

        # Both raw_code and code_session_memory_key provided
        r = execute_tool("code_interpreter", {
            "raw_code": "print('hi')",
            "code_session_memory_key": "some_key",
        }, env.session_data)
        cl.check(
            "both code sources",
            "Returns error when both raw_code and code_session_memory_key are given",
            r.startswith("Error:"),
            f"got: {r!r}",
        )

        # code_session_memory_key references a non-existent session memory key
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "nonexistent_key_xyz",
        }, env.session_data)
        cl.check(
            "missing code key",
            "Returns error when the session key holding code does not exist",
            r.startswith("Error:") and "nonexistent_key_xyz" in r,
            f"got: {r!r}",
        )

        # Seed a valid code key used for timeout/arg validation checks below
        mem["dummy_code"] = "print('ok')"

        # timeout is a bool — explicitly rejected by the schema validator
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "dummy_code",
            "timeout": True,
        }, env.session_data)
        cl.check(
            "timeout bool rejected",
            "Response mentions 'bool' when timeout is a bool value",
            "bool" in r,
            f"got: {r!r}",
        )

        # timeout below minimum (schema: minimum=1)
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "dummy_code",
            "timeout": 0,
        }, env.session_data)
        cl.check(
            "timeout too low",
            "Response mentions 'timeout' or 'minimum' when timeout is 0",
            "timeout" in r.lower() or "minimum" in r.lower(),
            f"got: {r!r}",
        )

        # timeout above maximum (schema: maximum=120)
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "dummy_code",
            "timeout": 121,
        }, env.session_data)
        cl.check(
            "timeout too high",
            "Response mentions 'timeout' or 'maximum' when timeout exceeds 120",
            "timeout" in r.lower() or "maximum" in r.lower(),
            f"got: {r!r}",
        )

        # session_memory_arg_keys references a missing session memory key
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "dummy_code",
            "session_memory_arg_keys": ["no_such_arg_key"],
        }, env.session_data)
        cl.check(
            "arg missing session key",
            "Returns error when a session_memory_arg_keys entry references a non-existent key",
            r.startswith("Error:") and "no_such_arg_key" in r,
            f"got: {r!r}",
        )

        # --- Execution tests (Piston required) ---
        if not _piston_available():
            cl.skip("Piston not reachable — execution tests skipped (run docker compose up piston)")
            return cl.result()

        # Basic: raw_code, no args, stdout returned directly
        r = execute_tool("code_interpreter", {
            "raw_code": "print('hello world')",
        }, env.session_data)
        cl.check("basic raw_code", "raw_code executes and returns stdout", "hello world" in r, f"got: {r!r}")

        # code from session memory key
        mem["code_hello"] = "print('from memory')\n"
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_hello",
        }, env.session_data)
        cl.check("code from session key", "code_session_memory_key executes code from memory", "from memory" in r, f"got: {r!r}")

        # sys_argv passed to the script
        mem["code_argv"] = (
            "import sys\n"
            "print(sys.argv[1])\n"
        )
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_argv",
            "sys_argv": ["argval"],
        }, env.session_data)
        cl.check("sys_argv", "sys_argv value appears in script output", "argval" in r, f"got: {r!r}")

        # session_memory_arg_keys: key holds a string appended to argv
        mem["the_word"] = "piston"
        mem["code_reverse"] = (
            "import sys\n"
            "print(sys.argv[1][::-1])\n"
        )
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_reverse",
            "session_memory_arg_keys": ["the_word"],
        }, env.session_data)
        cl.check(
            "session_memory_arg_keys",
            "session_memory_arg_keys passes string from session memory as argv; 'piston' reversed is 'notsip'",
            "notsip" in r,
            f"got: {r!r}",
        )

        # output_session_memory_key: stdout written to memory instead of returned
        mem["code_greeting"] = "print('greetings')\n"
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_greeting",
            "output_session_memory_key": "greeting_result",
        }, env.session_data)
        stored = mem.get("greeting_result")
        cl.check(
            "output_session_memory_key message",
            "Confirmation message mentions the output_session_memory_key",
            "greeting_result" in r,
            f"got: {r!r}",
        )
        cl.check(
            "output_session_memory_key stored",
            "Stdout was written into session memory",
            stored is not None and "greetings" in stored,
            f"stored: {stored!r}",
        )

        # Runtime error: non-zero exit code
        mem["code_crash"] = "raise ValueError('intentional')\n"
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_crash",
        }, env.session_data)
        cl.check(
            "runtime error",
            "A code exception produces an inline error response referencing exit code",
            "exit" in r.lower() or "failed" in r.lower(),
            f"got: {r!r}",
        )

        # enable_tracebacks=True: full traceback present
        r = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_crash",
            "enable_tracebacks": True,
        }, env.session_data)
        cl.check(
            "enable_tracebacks shows Traceback header",
            "With enable_tracebacks=True the output contains 'Traceback (most recent call last):'",
            "Traceback (most recent call last):" in r,
            f"got: {r!r}",
        )

        # enable_tracebacks=False: traceback stripped, exception summary kept
        r_no_tb = execute_tool("code_interpreter", {
            "code_session_memory_key": "code_crash",
            "enable_tracebacks": False,
        }, env.session_data)
        cl.check(
            "enable_tracebacks=False strips traceback",
            "With enable_tracebacks=False the output does NOT contain 'Traceback (most recent call last):'",
            "Traceback (most recent call last):" not in r_no_tb,
            f"got: {r_no_tb!r}",
        )
        cl.check(
            "enable_tracebacks=False keeps exception summary",
            "With enable_tracebacks=False the output still contains the exception type",
            "ValueError" in r_no_tb,
            f"got: {r_no_tb!r}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
