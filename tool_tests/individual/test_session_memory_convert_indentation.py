from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_convert_indentation")
    try:
        # spaces -> tabs
        env.session_data["memory"]["code"] = "def foo():\n    x = 1\n"
        r = execute_tool("session_memory_convert_indentation", {"key": "code", "to": "tabs", "spaces_per_tab": 4}, env.session_data)
        cl.check("spaces to tabs return", "Converting to tabs returns a success message", "tabs" in r.lower(), f"got: {r!r}")
        after_tabs = env.session_data["memory"].get("code", "")
        cl.check("tabs present", "Converted value contains tab character", "\t" in after_tabs, f"got: {after_tabs!r}")
        cl.check("4-space indent gone", "Converted value no longer has 4-space leading indent", "    x" not in after_tabs, f"got: {after_tabs!r}")

        # tabs -> spaces
        env.session_data["memory"]["code"] = "def foo():\n\tx = 1\n"
        r2 = execute_tool("session_memory_convert_indentation", {"key": "code", "to": "spaces", "spaces_per_tab": 4}, env.session_data)
        cl.check("tabs to spaces return", "Converting to spaces returns a success message", "spaces" in r2.lower(), f"got: {r2!r}")
        after_spaces = env.session_data["memory"].get("code", "")
        cl.check("spaces present", "Converted value contains 4-space indent", "    x" in after_spaces, f"got: {after_spaces!r}")
        cl.check("tab indent gone", "Converted value no longer has leading tab", "\tx" not in after_spaces, f"got: {after_spaces!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
