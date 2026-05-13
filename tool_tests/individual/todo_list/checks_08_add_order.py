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
    # list is now: 1=step ONE, 2=step two
    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "before": 2, "text": "inserted before 2"}, env.session_data)
    d = _j(r)
    cl.check("add_item before path", "Insert before 2 gives item_path='2'",
             d.get("item_path") == "2", f"got: {r!r}")
    r = execute_tool("todo_list", {"action": "get_item", "item_path": "2"}, env.session_data)
    cl.check("add_item before text", "Item at position 2 is the newly inserted item",
             r == "inserted before 2", f"got: {r!r}")

    # list is now: 1=step ONE, 2=inserted before 2, 3=step two
    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "after": 1, "text": "inserted after 1"}, env.session_data)
    d = _j(r)
    cl.check("add_item after path", "Insert after 1 gives item_path='2'",
             d.get("item_path") == "2", f"got: {r!r}")
    r = execute_tool("todo_list", {"action": "get_item", "item_path": "2"}, env.session_data)
    cl.check("add_item after text", "Item at position 2 is the after-inserted item",
             r == "inserted after 1", f"got: {r!r}")

