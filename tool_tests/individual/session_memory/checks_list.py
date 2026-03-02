from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    mem = env.session_data["memory"]
    mem["alpha"] = "1"
    mem["beta"] = "2"
    mem["gamma"] = "3"

    r = execute_tool("session_memory", {"action": "list"}, env.session_data)
    keys = r.strip().splitlines()
    cl.check("list: all", "Lists all keys", {"alpha", "beta", "gamma"}.issubset(set(keys)), f"got: {r!r}")

    r2 = execute_tool("session_memory", {"action": "list", "prefix": "al"}, env.session_data)
    cl.check("list: prefix filter", "Returns only keys matching prefix", "alpha" in r2 and "beta" not in r2, f"got: {r2!r}")

    r3 = execute_tool("session_memory", {"action": "list", "limit": 1}, env.session_data)
    cl.check("list: limit", "Limits number of returned keys", len(r3.strip().splitlines()) == 1, f"got: {r3!r}")
