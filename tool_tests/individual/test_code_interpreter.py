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
    try:
        # --- Validation tests (no Piston needed) ---

        # target=session_memory without memory_key
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "x",
            "target": "session_memory",
        }, env.session_data)
        cl.check(
            "missing memory_key",
            "Returns error when target=session_memory but memory_key is absent",
            r.startswith("Error:") and "memory_key" in r,
            f"got: {r!r}",
        )

        # Code key not in session memory
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "nonexistent_key_xyz",
        }, env.session_data)
        cl.check(
            "missing code key",
            "Returns error when the session key holding code does not exist",
            r.startswith("Error:") and "nonexistent_key_xyz" in r,
            f"got: {r!r}",
        )

        # Seed a dummy code key used for timeout/arg validation checks below
        env.session_data["memory"]["dummy_code"] = "def main(): return ''"

        # Timeout: bool is explicitly rejected (bool is a subclass of int in Python).
        # execute_tool validates args against the JSON schema before calling execute(),
        # so the error prefix is "Failed to execute tool" not "Error:" — check for
        # the specific discriminating token instead.
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "timeout": True,
        }, env.session_data)
        cl.check(
            "timeout bool rejected",
            "Response mentions 'bool' when timeout is a bool value",
            "bool" in r,
            f"got: {r!r}",
        )

        # Timeout: below minimum (0)
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "timeout": 0,
        }, env.session_data)
        cl.check(
            "timeout too low",
            "Response mentions 'timeout' or 'minimum' when timeout is 0",
            "timeout" in r.lower() or "minimum" in r.lower(),
            f"got: {r!r}",
        )

        # Timeout: above maximum (121)
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "timeout": 121,
        }, env.session_data)
        cl.check(
            "timeout too high",
            "Response mentions 'timeout' or 'maximum' when timeout exceeds 120",
            "timeout" in r.lower() or "maximum" in r.lower(),
            f"got: {r!r}",
        )

        # Args: element references a missing session memory key
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "args": [{"session_memory_key": "no_such_arg_key"}],
        }, env.session_data)
        cl.check(
            "arg missing session key",
            "Returns error when an arg dict references a non-existent session key",
            r.startswith("Error:") and "no_such_arg_key" in r,
            f"got: {r!r}",
        )

        # --- Execution tests (Piston required) ---
        if not _piston_available():
            cl.skip("Piston not reachable — execution tests skipped (run docker compose up piston)")
            return cl.result()

        # Basic: constant return value
        env.session_data["memory"]["code_hello"] = (
            "def main():\n"
            "    return 'hello world'\n"
        )
        r = execute_tool("code_interpreter", {"session_memory_key_code": "code_hello"}, env.session_data)
        cl.check("basic execution", "main() with no args returns a string constant", r == "hello world", f"got: {r!r}")

        # Single string arg: upper-case
        env.session_data["memory"]["code_upper"] = (
            "def main(x):\n"
            "    return x.upper()\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_upper",
            "args": ["hello"],
        }, env.session_data)
        cl.check("string arg", "main(x) receives a plain string arg and returns x.upper()", r == "HELLO", f"got: {r!r}")

        # Multiple string args: integer addition
        env.session_data["memory"]["code_add"] = (
            "def main(a, b):\n"
            "    return str(int(a) + int(b))\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_add",
            "args": ["7", "13"],
        }, env.session_data)
        cl.check("multiple numeric args", "main(a, b) parses strings as ints and returns their sum", r == "20", f"got: {r!r}")

        # Arg loaded from session memory via session_memory_key dict
        env.session_data["memory"]["the_word"] = "piston"
        env.session_data["memory"]["code_reverse"] = (
            "def main(w):\n"
            "    return w[::-1]\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_reverse",
            "args": [{"session_memory_key": "the_word"}],
        }, env.session_data)
        cl.check(
            "arg from session memory",
            "Arg loaded from session key 'the_word' ('piston') reversed is 'notsip'",
            r == "notsip",
            f"got: {r!r}",
        )

        # Helper function alongside main()
        env.session_data["memory"]["code_helpers"] = (
            "def _double(n):\n"
            "    return n * 2\n"
            "\n"
            "def main(x):\n"
            "    return str(_double(int(x)))\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_helpers",
            "args": ["6"],
        }, env.session_data)
        cl.check("helper function", "Code with a helper function alongside main() executes correctly", r == "12", f"got: {r!r}")

        # JSON return value
        env.session_data["memory"]["code_json"] = (
            "import json\n"
            "\n"
            "def main():\n"
            "    return json.dumps({'status': 'ok', 'n': 42})\n"
        )
        r = execute_tool("code_interpreter", {"session_memory_key_code": "code_json"}, env.session_data)
        try:
            parsed = _json.loads(r)
            json_ok = parsed.get("status") == "ok" and parsed.get("n") == 42
        except Exception:
            json_ok = False
        cl.check("json return", "main() returns a valid JSON string with expected fields", json_ok, f"got: {r!r}")

        # target=session_memory: result stored, confirmation message returned
        env.session_data["memory"]["code_greeting"] = (
            "def main():\n"
            "    return 'greetings'\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_greeting",
            "target": "session_memory",
            "memory_key": "greeting_result",
        }, env.session_data)
        stored = env.session_data["memory"].get("greeting_result")
        cl.check(
            "target session_memory message",
            "Confirmation message mentions the memory key when target=session_memory",
            "greeting_result" in r,
            f"got: {r!r}",
        )
        cl.check(
            "target session_memory stored",
            "Execution result is actually written into the named session memory key",
            stored == "greetings",
            f"stored: {stored!r}",
        )

        # Runtime error: code raises an exception -> non-zero exit code error
        env.session_data["memory"]["code_crash"] = (
            "def main():\n"
            "    raise ValueError('intentional error')\n"
        )
        r = execute_tool("code_interpreter", {"session_memory_key_code": "code_crash"}, env.session_data)
        cl.check(
            "runtime error",
            "A code exception produces an error response referencing a non-zero exit code",
            r.startswith("Error:") and "exit" in r.lower(),
            f"got: {r!r}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
