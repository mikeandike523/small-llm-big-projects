from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_list_variables")
    try:
        mem = env.session_data["memory"]
        mem["alpha"] = "1"
        mem["beta"] = "2"
        mem["gamma"] = "3"

        # list all
        r = execute_tool("session_memory_list_variables", {}, env.session_data)
        keys = r.strip().splitlines()
        cl.check("list all", "Lists all keys", set(["alpha", "beta", "gamma"]).issubset(set(keys)), f"got: {r!r}")

        # prefix filter
        r2 = execute_tool("session_memory_list_variables", {"prefix": "al"}, env.session_data)
        cl.check("prefix filter", "Returns only keys matching prefix", "alpha" in r2 and "beta" not in r2, f"got: {r2!r}")

        # limit
        r3 = execute_tool("session_memory_list_variables", {"limit": 1}, env.session_data)
        cl.check("limit", "Limits number of returned keys", len(r3.strip().splitlines()) == 1, f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
