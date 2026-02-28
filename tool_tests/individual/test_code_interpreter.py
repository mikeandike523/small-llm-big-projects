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

        # target=session_memory without target_session_memory_key
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy",
            "target": "session_memory",
        }, env.session_data)
        cl.check(
            "target_session_memory_key required",
            "Returns error when target=session_memory but target_session_memory_key is absent",
            r.startswith("Error:") and "target_session_memory_key" in r,
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
        mem["dummy_code"] = "def main(): return ''"

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

        # Literal arg that is not valid JSON
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "args": ["not valid json{"],
        }, env.session_data)
        cl.check(
            "invalid json literal arg",
            "Returns error when a literal arg string is not valid JSON",
            r.startswith("Error:") and "JSON" in r,
            f"got: {r!r}",
        )

        # session_memory_key arg references a missing session memory key
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "args": [{"session_memory_key": "no_such_arg_key"}],
        }, env.session_data)
        cl.check(
            "arg missing session key",
            "Returns error when a session_memory_key arg references a non-existent key",
            r.startswith("Error:") and "no_such_arg_key" in r,
            f"got: {r!r}",
        )

        # session_memory_key arg whose stored value is not valid JSON
        mem["bad_json_arg"] = "not valid json{"
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "dummy_code",
            "args": [{"session_memory_key": "bad_json_arg"}],
        }, env.session_data)
        cl.check(
            "arg session key holds invalid json",
            "Returns error when session memory arg value is not valid JSON",
            r.startswith("Error:") and "JSON" in r,
            f"got: {r!r}",
        )

        # --- Execution tests (Piston required) ---
        if not _piston_available():
            cl.skip("Piston not reachable — execution tests skipped (run docker compose up piston)")
            return cl.result()

        # Basic: no args, returns a string. Pipeline: json.dumps("hello world") -> '"hello world"'
        mem["code_hello"] = (
            "def main():\n"
            "    return 'hello world'\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_hello",
        }, env.session_data)
        cl.check("basic execution", "main() returns string; result is JSON-encoded inline", _json.loads(r) == "hello world", f"got: {r!r}")

        # Literal string arg: pass '"hello"' (JSON-encoded string) -> main receives str "hello"
        mem["code_upper"] = (
            "def main(x):\n"
            "    return x.upper()\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_upper",
            "args": ['"hello"'],
        }, env.session_data)
        cl.check("literal string arg", "JSON-encoded string arg decoded; main receives str and returns upper", _json.loads(r) == "HELLO", f"got: {r!r}")

        # Literal number args: "7" and "13" decoded to ints 7 and 13
        mem["code_add"] = (
            "def main(a, b):\n"
            "    return a + b\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_add",
            "args": ["7", "13"],
        }, env.session_data)
        cl.check("literal number args", "JSON number args decoded to ints; 7 + 13 = 20", _json.loads(r) == 20, f"got: {r!r}")

        # session_memory_key arg: "the_word" holds '"piston"' (JSON-encoded string)
        mem["the_word"] = '"piston"'
        mem["code_reverse"] = (
            "def main(w):\n"
            "    return w[::-1]\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_reverse",
            "args": [{"session_memory_key": "the_word"}],
        }, env.session_data)
        cl.check(
            "session_memory_key arg",
            "JSON value from session memory decoded; 'piston' reversed is 'notsip'",
            _json.loads(r) == "notsip",
            f"got: {r!r}",
        )

        # Mix: one literal number, one session memory arg
        mem["multiplier"] = "3"   # JSON number 3
        mem["code_mul"] = (
            "def main(a, b):\n"
            "    return a * b\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_mul",
            "args": ["7", {"session_memory_key": "multiplier"}],
        }, env.session_data)
        cl.check("mixed args", "Literal + session_memory_key args: 7 * 3 = 21", _json.loads(r) == 21, f"got: {r!r}")

        # List arg from session memory
        mem["numbers"] = "[10, 20, 30]"   # JSON array
        mem["code_sum"] = (
            "def main(nums):\n"
            "    return sum(nums)\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_sum",
            "args": [{"session_memory_key": "numbers"}],
        }, env.session_data)
        cl.check("list arg from session memory", "JSON list [10,20,30] decoded; sum = 60", _json.loads(r) == 60, f"got: {r!r}")

        # Return a dict directly (no manual json.dumps needed in user code)
        mem["code_dict"] = (
            "def main():\n"
            "    return {'status': 'ok', 'n': 42}\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_dict",
        }, env.session_data)
        parsed = _json.loads(r)
        cl.check("dict return value", "main() returns a dict; tool JSON-encodes it automatically", parsed == {"status": "ok", "n": 42}, f"got: {r!r}")

        # Helper function alongside main()
        mem["code_helpers"] = (
            "def _double(n):\n"
            "    return n * 2\n"
            "\n"
            "def main(x):\n"
            "    return _double(x)\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_helpers",
            "args": ["6"],
        }, env.session_data)
        cl.check("helper function", "Helper function used; _double(6) = 12", _json.loads(r) == 12, f"got: {r!r}")

        # target=session_memory: JSON-encoded result stored, confirmation returned
        mem["code_greeting"] = (
            "def main():\n"
            "    return 'greetings'\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_greeting",
            "target": "session_memory",
            "target_session_memory_key": "greeting_result",
        }, env.session_data)
        stored = mem.get("greeting_result")
        cl.check(
            "target session_memory message",
            "Confirmation message mentions the target_session_memory_key",
            "greeting_result" in r,
            f"got: {r!r}",
        )
        cl.check(
            "target session_memory stored as json",
            "Result stored as JSON-encoded string in session memory",
            _json.loads(stored) == "greetings",
            f"stored: {stored!r}",
        )

        # Runtime error: code raises an exception -> error returned inline
        mem["code_crash"] = (
            "def main():\n"
            "    raise ValueError('intentional error')\n"
        )
        r = execute_tool("code_interpreter", {
            "session_memory_key_code": "code_crash",
        }, env.session_data)
        cl.check(
            "runtime error",
            "A code exception produces an inline error response referencing a non-zero exit code",
            r.startswith("Error:") and "exit" in r.lower(),
            f"got: {r!r}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
