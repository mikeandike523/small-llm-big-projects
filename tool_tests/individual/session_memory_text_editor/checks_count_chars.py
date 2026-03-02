from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["mystr"] = "hello"
    r = execute_tool("session_memory_text_editor", {"action": "count_chars", "key": "mystr"}, env.session_data)
    cl.check("count_chars: known string", "Returns char count for known string", "5" in r, f"got: {r!r}")

    r2 = execute_tool("session_memory_text_editor", {"action": "count_chars", "key": "nosuch"}, env.session_data)
    cl.check("count_chars: missing key error", "Returns error for missing key", "Error" in r2 or "not found" in r2.lower(), f"got: {r2!r}")
