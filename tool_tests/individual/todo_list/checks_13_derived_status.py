from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def _j(r: str) -> dict:
    # Structure-changing actions append a reminder block after the JSON;
    # strip it before parsing the JSON portion of the result.
    marker = "\n\n<system-reminder>"
    if marker in r:
        r = r.split(marker, 1)[0]
    try:
        return json.loads(r)
    except Exception:
        return {}


def add_checks(cl: CheckList, env: TestEnv) -> None:
    dc: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dc
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child 1"}, dc
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child 2"}, dc
    )

    # Close one child — parent stays open
    execute_tool("todo_list", {"action": "close_item", "item_path": "1.1"}, dc)
    r = execute_tool("todo_list", {"action": "list"}, dc)
    root_item = _j(r).get("items", [{}])[0]
    cl.check(
        "promoted partial close stays open",
        "Promoted item is open when only one child closed",
        root_item.get("status") == "open",
        f"got: {root_item!r}",
    )

    # Close second child — parent becomes closed
    execute_tool("todo_list", {"action": "close_item", "item_path": "1.2"}, dc)
    r = execute_tool("todo_list", {"action": "list"}, dc)
    root_item = _j(r).get("items", [{}])[0]
    cl.check(
        "promoted all children closed",
        "Promoted item is closed when all children closed",
        root_item.get("status") == "closed",
        f"got: {root_item!r}",
    )
