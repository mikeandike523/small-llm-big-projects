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
    r = execute_tool(
        "todo_list", {"action": "close_item", "item_path": "1"}, env.session_data
    )
    d = _j(r)
    cl.check(
        "close_item status",
        "close_item returns status='closed'",
        d.get("status") == "closed",
        f"got: {r!r}",
    )

    r = execute_tool("todo_list", {"action": "list"}, env.session_data)
    items = _j(r).get("items", [])
    cl.check(
        "close_item reflected in list",
        "Closed item shows status='closed' in list",
        items[0].get("status") == "closed",
        f"got: {items!r}",
    )

    r = execute_tool("todo_list", {"action": "list_formatted"}, env.session_data)
    cl.check(
        "list_formatted closed checkbox",
        "Closed item shows [x] in formatted output",
        "[x]" in r,
        f"got: {r!r}",
    )

    r = execute_tool(
        "todo_list", {"action": "reopen_item", "item_path": "1"}, env.session_data
    )
    cl.check(
        "reopen_item status",
        "reopen_item returns status='open'",
        _j(r).get("status") == "open",
        f"got: {r!r}",
    )
