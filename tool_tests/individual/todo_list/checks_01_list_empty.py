from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def _j(r: str) -> dict:
    try:
        return json.loads(r)
    except Exception:
        return {}


def add_checks(cl: CheckList, env: TestEnv) -> None:
    r = execute_tool("todo_list", {"action": "list"}, env.session_data)
    cl.check(
        "list empty",
        "Empty list returns items=[]",
        _j(r).get("items") == [],
        f"got: {r!r}",
    )

    r = execute_tool("todo_list", {"action": "list_formatted"}, env.session_data)
    cl.check(
        "list_formatted empty",
        "Empty list returns '(empty todo list)'",
        r == "(empty todo list)",
        f"got: {r!r}",
    )
