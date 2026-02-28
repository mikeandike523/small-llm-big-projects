from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_check_indentation")
    try:
        # 4-space indented code
        env.session_data["memory"]["code"] = "def foo():\n    x = 1\n    return x\n"
        r_spaces = execute_tool("session_memory_check_indentation", {"key": "code"}, env.session_data)
        cl.check("spaces detected", "Result mentions 'spaces' for space-indented code", "spaces" in r_spaces.lower(), f"got: {r_spaces!r}")

        # tab indented code
        env.session_data["memory"]["code"] = "def foo():\n\tx = 1\n\treturn x\n"
        r_tabs = execute_tool("session_memory_check_indentation", {"key": "code"}, env.session_data)
        cl.check("tabs detected", "Result mentions 'tabs' for tab-indented code", "tabs" in r_tabs.lower(), f"got: {r_tabs!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
