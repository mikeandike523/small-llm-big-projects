from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_count_chars")
    try:
        env.session_data["memory"]["mystr"] = "hello"
        r = execute_tool("session_memory_count_chars", {"key": "mystr"}, env.session_data)
        cl.check("count chars", "Returns char count for known string", "5" in r, f"got: {r!r}")

        # missing key
        r2 = execute_tool("session_memory_count_chars", {"key": "nosuch"}, env.session_data)
        cl.check("missing key error", "Returns error for missing key", "Error" in r2 or "not found" in r2.lower(), f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
