from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("project_memory_set_variable")
    try:
        # set literal value
        r = execute_tool("project_memory_set_variable", {"key": "testkey", "value": "testval"}, env.session_data)
        cl.check("set literal value", "Stores a literal value in project memory", "Stored" in r, f"got: {r!r}")

        # set from session key
        env.session_data["memory"]["sesskey"] = "fromSession"
        r2 = execute_tool("project_memory_set_variable", {"key": "testkey2", "from_session_key": "sesskey"}, env.session_data)
        cl.check("set from session key", "Copies value from session memory into project memory", "Stored" in r2, f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
