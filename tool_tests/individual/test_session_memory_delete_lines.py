from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_delete_lines")
    try:
        # delete first line
        env.session_data["memory"]["key"] = "a\nb\nc\nd\n"
        r = execute_tool("session_memory_delete_lines", {"key": "key", "start_line": 1, "end_line": 1}, env.session_data)
        cl.check("delete first line return", "Deleting line 1 returns a success message", "Deleted" in r, f"got: {r!r}")
        after_first = env.session_data["memory"].get("key", "")
        cl.check("first line removed", "Value no longer starts with 'a'", not after_first.startswith("a"), f"got: {after_first!r}")
        cl.check("second line is now first", "Value now starts with 'b'", after_first.startswith("b"), f"got: {after_first!r}")

        # delete range lines 2-3 from the remainder (b, c, d -> delete c and d)
        # after_first is "b\nc\nd\n"; lines 2-3 are c and d
        r2 = execute_tool("session_memory_delete_lines", {"key": "key", "start_line": 2, "end_line": 3}, env.session_data)
        cl.check("delete range return", "Deleting lines 2-3 returns a success message", "Deleted" in r2, f"got: {r2!r}")
        after_range = env.session_data["memory"].get("key", "")
        cl.check("range removed", "Only 'b' line remains", after_range.strip() == "b", f"got: {after_range!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
