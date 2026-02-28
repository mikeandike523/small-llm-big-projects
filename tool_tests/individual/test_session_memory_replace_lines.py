from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_replace_lines")
    try:
        # replace single line: line 2 ("b") -> "B"
        env.session_data["memory"]["key"] = "a\nb\nc\n"
        r = execute_tool("session_memory_replace_lines", {"key": "key", "start_line": 2, "end_line": 2, "text": "B"}, env.session_data)
        cl.check("replace single line return", "Replacing line 2 returns a success message", "Replaced" in r, f"got: {r!r}")
        after_single = env.session_data["memory"].get("key", "")
        cl.check("line 2 replaced", "Second line is now 'B'", "B" in after_single, f"got: {after_single!r}")
        cl.check("old line 2 gone", "Original 'b' is no longer present", "\nb\n" not in after_single, f"got: {after_single!r}")

        # replace range: lines 1-2 -> "X\nY"
        env.session_data["memory"]["key"] = "a\nb\nc\n"
        r2 = execute_tool("session_memory_replace_lines", {"key": "key", "start_line": 1, "end_line": 2, "text": "X\nY"}, env.session_data)
        cl.check("replace range return", "Replacing lines 1-2 returns a success message", "Replaced" in r2, f"got: {r2!r}")
        after_range = env.session_data["memory"].get("key", "")
        lines = after_range.splitlines()
        cl.check("range first line is X", "First line is now 'X'", len(lines) >= 1 and lines[0] == "X", f"got lines: {lines!r}")
        cl.check("range second line is Y", "Second line is now 'Y'", len(lines) >= 2 and lines[1] == "Y", f"got lines: {lines!r}")
        cl.check("range third line is c", "Third line is still 'c'", len(lines) >= 3 and lines[2] == "c", f"got lines: {lines!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
