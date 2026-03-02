from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["text"] = "line1\nline2\nline3\n"
    r = execute_tool("session_memory_text_editor", {"action": "insert_lines", "key": "text", "before_line": 1, "text": "line0"}, env.session_data)
    cl.check("insert_lines: prepend return", "Inserting before line 1 returns a success message", "Inserted" in r, f"got: {r!r}")

    after_prepend = env.session_data["memory"].get("text", "")
    cl.check("insert_lines: prepend starts with line0", "line0 is now the first line", after_prepend.startswith("line0"), f"got: {after_prepend!r}")
    cl.check("insert_lines: prepend preserves line1", "Original line1 is still present", "line1" in after_prepend, f"got: {after_prepend!r}")

    env.session_data["memory"]["text"] = "line1\nline2\nline3\n"
    r2 = execute_tool("session_memory_text_editor", {"action": "insert_lines", "key": "text", "before_line": 99, "text": "appended"}, env.session_data)
    cl.check("insert_lines: append return", "Inserting before a line beyond end returns a success message", "Inserted" in r2, f"got: {r2!r}")

    after_append = env.session_data["memory"].get("text", "")
    cl.check("insert_lines: append result ends with appended", "New text appears at the end",
             after_append.rstrip("\n").endswith("appended"), f"got: {after_append!r}")
