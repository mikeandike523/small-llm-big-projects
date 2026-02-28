from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("project_memory_delete_variable")
    try:
        # set a key then delete it
        execute_tool("project_memory_set_variable", {"key": "delme", "value": "gone"}, env.session_data)
        r = execute_tool("project_memory_delete_variable", {"key": "delme"}, env.session_data)
        cl.check("delete existing", "Delete returns success message", "Deleted" in r, f"got: {r!r}")

        # get after delete should return not found
        r2 = execute_tool("project_memory_get_variable", {"key": "delme"}, env.session_data)
        cl.check("key gone after delete", "Getting deleted key returns not-found message", "not found" in r2, f"got: {r2!r}")

        # delete non-existent key - check if graceful (not an exception)
        r3 = execute_tool("project_memory_delete_variable", {"key": "nosuchkey"}, env.session_data)
        cl.check("delete non-existent graceful", "Deleting missing key responds gracefully without crashing", isinstance(r3, str) and len(r3) > 0, f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
