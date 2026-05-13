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
    ms: dict = {}
    execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "A"}, ms)
    execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "B"}, ms)

    r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": "", "texts": ["X", "Y", "Z"]}, ms)
    d = _j(r)
    added = d.get("items", [])
    cl.check("add_many_items count", "add_many_items returns 3 items",
             len(added) == 3, f"got: {r!r}")
    cl.check("add_many_items paths", "add_many_items items have correct paths",
             [it["item_path"] for it in added] == ["3", "4", "5"], f"got: {added!r}")

    r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": "", "before": 1, "texts": ["first", "second"]}, ms)
    d = _j(r)
    added = d.get("items", [])
    cl.check("add_many_items before paths", "add_many_items before=1 gives paths 1 and 2",
             [it["item_path"] for it in added] == ["1", "2"], f"got: {added!r}")
    r = execute_tool("todo_list", {"action": "get_item", "item_path": "1"}, ms)
    cl.check("add_many_items before text", "First item is now 'first'",
             r == "first", f"got: {r!r}")

