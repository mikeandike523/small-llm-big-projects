from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["todelete"] = "x"

    r = execute_tool("session_memory", {"action": "delete", "key": "todelete"}, env.session_data)
    cl.check("delete: existing", "Delete returns success message", "Deleted" in r or "deleted" in r.lower(), f"got: {r!r}")
    cl.check("delete: key gone", "Key is no longer in memory", "todelete" not in env.session_data["memory"], "key still present")

    r2 = execute_tool("session_memory", {"action": "delete", "key": "nosuchkey"}, env.session_data)
    cl.check("delete: missing raises", "Deleting missing key returns error string with 'does not exist'",
             "Failed" in r2 and "does not exist" in r2, f"got: {r2!r}")
