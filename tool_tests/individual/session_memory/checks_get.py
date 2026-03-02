from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["mykey"] = "hello world"

    r = execute_tool("session_memory", {"action": "get", "key": "mykey"}, env.session_data)
    cl.check("get: existing", "Returns the stored value", r == "hello world", f"got: {r!r}")

    r2 = execute_tool("session_memory", {"action": "get", "key": "nosuchkey"}, env.session_data)
    cl.check("get: missing key returns not found", "Returns not-found message for absent key", "not found" in r2, f"got: {r2!r}")

    env.session_data["memory"]["lines"] = "line1\nline2\nline3"
    r3 = execute_tool("session_memory", {"action": "get", "key": "lines", "number_lines": True}, env.session_data)
    cl.check("get: number_lines=True", "Returns line-numbered view", "1" in r3 and "line1" in r3, f"got: {r3!r}")
