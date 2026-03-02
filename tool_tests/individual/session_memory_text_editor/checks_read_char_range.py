from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["str"] = "0123456789"

    r = execute_tool("session_memory_text_editor", {"action": "read_char_range", "key": "str"}, env.session_data)
    cl.check("read_char_range: full read", "Reading without start/end returns the entire value", r == "0123456789", f"got: {r!r}")

    r2 = execute_tool("session_memory_text_editor", {"action": "read_char_range", "key": "str", "start_char": 2, "end_char": 5}, env.session_data)
    cl.check("read_char_range: partial read", "start_char=2, end_char=5 returns chars at indices 2,3,4", r2 == "234", f"got: {r2!r}")
