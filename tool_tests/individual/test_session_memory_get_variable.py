from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_get_variable")
    try:
        env.session_data["memory"]["mykey"] = "hello world"

        # get existing
        r = execute_tool("session_memory_get_variable", {"key": "mykey"}, env.session_data)
        cl.check("get existing", "Returns the stored value", r == "hello world", f"got: {r!r}")

        # missing key
        r2 = execute_tool("session_memory_get_variable", {"key": "nosuchkey"}, env.session_data)
        cl.check("missing key returns not found", "Returns not-found message for absent key", "not found" in r2, f"got: {r2!r}")

        # number_lines=True
        env.session_data["memory"]["lines"] = "line1\nline2\nline3"
        r3 = execute_tool("session_memory_get_variable", {"key": "lines", "number_lines": True}, env.session_data)
        cl.check("number_lines=True", "Returns line-numbered view", "1" in r3 and "line1" in r3, f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
