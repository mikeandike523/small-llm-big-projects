from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["code"] = "def foo():\n    x = 1\n    return x\n"
    r_spaces = execute_tool("session_memory_text_editor", {"action": "check_indentation", "key": "code"}, env.session_data)
    cl.check("check_indentation: spaces detected", "Result mentions 'spaces' for space-indented code", "spaces" in r_spaces.lower(), f"got: {r_spaces!r}")

    env.session_data["memory"]["code"] = "def foo():\n\tx = 1\n\treturn x\n"
    r_tabs = execute_tool("session_memory_text_editor", {"action": "check_indentation", "key": "code"}, env.session_data)
    cl.check("check_indentation: tabs detected", "Result mentions 'tabs' for tab-indented code", "tabs" in r_tabs.lower(), f"got: {r_tabs!r}")
