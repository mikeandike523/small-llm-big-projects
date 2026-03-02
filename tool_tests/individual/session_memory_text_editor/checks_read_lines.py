from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["text"] = "line1\nline2\nline3\nline4\n"

    r = execute_tool("session_memory_text_editor", {"action": "read_lines", "key": "text"}, env.session_data)
    cl.check("read_lines: read all", "Returns full content when no range given", "line1" in r and "line4" in r, f"got: {r!r}")

    r2 = execute_tool("session_memory_text_editor", {"action": "read_lines", "key": "text", "start_line": 2, "end_line": 3}, env.session_data)
    cl.check("read_lines: partial range", "Returns only lines 2-3",
             "line2" in r2 and "line3" in r2 and "line4" not in r2, f"got: {r2!r}")

    r3 = execute_tool("session_memory_text_editor", {"action": "read_lines", "key": "text", "number_lines": True}, env.session_data)
    cl.check("read_lines: number_lines", "Returns line-numbered output", "1" in r3 and "line1" in r3, f"got: {r3!r}")
