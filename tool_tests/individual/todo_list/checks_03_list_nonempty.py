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
    items = _j(r).get("items", [])
    cl.check(
        "list three items count", "list returns 3 items", len(items) == 3, f"got: {r!r}"
    )
    cl.check(
        "list item_path field",
        "Items have item_path field",
        items[0].get("item_path") == "1" and items[2].get("item_path") == "3",
        f"got: {items!r}",
    )
    cl.check(
        "list status open",
        "Newly added items have status 'open'",
        all(it.get("status") == "open" for it in items),
        f"got: {items!r}",
    )

    r = execute_tool("todo_list", {"action": "list_formatted"}, env.session_data)
    cl.check(
        "list_formatted has items",
        "Formatted output contains both items",
        "step one" in r and "step two" in r,
        f"got: {r!r}",
    )
    cl.check(
        "list_formatted checkboxes",
        "Formatted output uses [ ] for open items",
        "[ ]" in r,
        f"got: {r!r}",
    )
    cl.check(
        "list_formatted path notation",
        "Formatted output uses dot-path notation",
        "1." in r and "2." in r,
        f"got: {r!r}",
    )
