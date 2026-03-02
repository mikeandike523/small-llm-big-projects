from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["lines"] = "a\nb\nc"
    r = execute_tool("session_memory_text_editor", {"action": "count_lines", "key": "lines"}, env.session_data)
    cl.check("count_lines: multiline string", "Returns line count for known multiline string", "3" in r, f"got: {r!r}")
