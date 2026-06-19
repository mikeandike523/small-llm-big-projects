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
    dh: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dh
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child"}, dh
    )

    r = execute_tool("todo_list", {"action": "delete_item", "item_path": "1"}, dh)
    d = _j(r)
    cl.check(
        "delete_item with children no cascade",
        "delete_item on item with children errors without cascade",
        "error" in d,
        f"got: {r!r}",
    )
    cl.check(
        "delete_item directive",
        "Error message mentions cascade_delete=true",
        "cascade_delete" in d.get("error", ""),
        f"got: {d.get('error')!r}",
    )

    r = execute_tool(
        "todo_list",
        {"action": "delete_item", "item_path": "1", "cascade_delete": True},
        dh,
    )
    cl.check(
        "delete_item cascade success",
        "cascade_delete=true removes item and children",
        "error" not in _j(r),
        f"got: {r!r}",
    )
    r = execute_tool("todo_list", {"action": "list"}, dh)
    cl.check(
        "delete_item cascade list empty",
        "List is empty after cascade delete",
        _j(r).get("items") == [],
        f"got: {r!r}",
    )
