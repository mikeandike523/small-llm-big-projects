from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("project_memory_get_variable")
    try:
        # set a value first, then get it back
        execute_tool("project_memory_set_variable", {"key": "gettest", "value": "myvalue"}, env.session_data)
        r = execute_tool("project_memory_get_variable", {"key": "gettest"}, env.session_data)
        cl.check("get existing value", "Returns the stored value inline", r == "myvalue", f"got: {r!r}")

        # get missing key
        r2 = execute_tool("project_memory_get_variable", {"key": "nosuchkey"}, env.session_data)
        cl.check("missing key returns not found", "Returns not-found message for absent key", "not found" in r2, f"got: {r2!r}")

        # get to session_memory
        execute_tool("project_memory_set_variable", {"key": "loadme", "value": "loaded_content"}, env.session_data)
        r3 = execute_tool("project_memory_get_variable", {"key": "loadme", "target": "session_memory", "target_session_key": "loaded"}, env.session_data)
        cl.check("get to session_memory result", "Returns confirmation message when writing to session memory", "loaded" in r3.lower(), f"got: {r3!r}")
        session_val = env.session_data["memory"].get("loaded")
        cl.check("get to session_memory value", "Value is written into session memory at the specified key", session_val == "loaded_content", f"got: {session_val!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
