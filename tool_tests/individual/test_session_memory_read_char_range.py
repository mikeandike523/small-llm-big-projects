from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_read_char_range")
    try:
        env.session_data["memory"]["str"] = "0123456789"

        # read full range (no start/end params)
        r = execute_tool("session_memory_read_char_range", {"key": "str"}, env.session_data)
        cl.check("full read", "Reading without start/end returns the entire value", r == "0123456789", f"got: {r!r}")

        # read start_char=2, end_char=5 -> "234"
        r2 = execute_tool("session_memory_read_char_range", {"key": "str", "start_char": 2, "end_char": 5}, env.session_data)
        cl.check("partial read", "start_char=2, end_char=5 returns chars at indices 2,3,4", r2 == "234", f"got: {r2!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
