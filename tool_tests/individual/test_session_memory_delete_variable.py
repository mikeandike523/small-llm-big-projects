from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_delete_variable")
    try:
        env.session_data["memory"]["todelete"] = "x"

        r = execute_tool("session_memory_delete_variable", {"key": "todelete"}, env.session_data)
        cl.check("delete existing", "Delete returns success message", "Deleted" in r or "deleted" in r.lower(), f"got: {r!r}")
        cl.check("key gone", "Key is no longer in memory", "todelete" not in env.session_data["memory"], "key still present")

        # delete non-existent key - execute_tool wraps the raised ValueError into an error string
        r2 = execute_tool("session_memory_delete_variable", {"key": "nosuchkey"}, env.session_data)
        cl.check("delete missing raises", "Deleting missing key returns error string with 'does not exist'", "Failed" in r2 and "does not exist" in r2, f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
