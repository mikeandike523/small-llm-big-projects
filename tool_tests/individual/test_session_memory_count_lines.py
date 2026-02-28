from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_count_lines")
    try:
        env.session_data["memory"]["lines"] = "a\nb\nc"
        r = execute_tool("session_memory_count_lines", {"key": "lines"}, env.session_data)
        cl.check("count lines", "Returns line count for known multiline string", "3" in r, f"got: {r!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
