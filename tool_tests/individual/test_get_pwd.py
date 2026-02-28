from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("get_pwd")
    try:
        # basic call — should return a non-empty string
        r = execute_tool("get_pwd", {}, env.session_data)
        cl.check("returns non-empty", "Returns a non-empty string for the cwd", isinstance(r, str) and len(r) > 0, f"got: {r!r}")

        # target=session_memory stores result in memory
        r2 = execute_tool("get_pwd", {"target": "session_memory", "memory_key": "pwd_result"}, env.session_data)
        cl.check("session_memory result mentions session memory", "Result message references session memory", "session memory" in r2.lower(), f"got: {r2!r}")

        stored = env.session_data["memory"].get("pwd_result")
        cl.check("session_memory value non-empty", "Stored pwd value is non-empty", isinstance(stored, str) and len(stored) > 0, f"got: {stored!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
