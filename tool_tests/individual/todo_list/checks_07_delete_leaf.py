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
    execute_tool("todo_list", {"action": "delete_item", "item_path": "3"}, env.session_data)
    r = execute_tool("todo_list", {"action": "list"}, env.session_data)
    items = _j(r).get("items", [])
    cl.check("delete_item leaf", "List has 2 items after deleting item 3",
             len(items) == 2, f"got: {r!r}")

