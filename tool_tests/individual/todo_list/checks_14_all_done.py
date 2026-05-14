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
    ad: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "only task"}, ad
    )
    r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, ad)
    msg = _j(r).get("message", "")
    cl.check(
        "all done message",
        "Closing last item triggers all-done notice",
        "all todo list items are now complete" in msg,
        f"got: {r!r}",
    )

    # all-done requires ALL closed (including promoted items via children)
    ad2: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, ad2
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child"}, ad2
    )
    r = execute_tool("todo_list", {"action": "close_item", "item_path": "1.1"}, ad2)
    msg = _j(r).get("message", "")
    cl.check(
        "all done via promoted item",
        "Closing last leaf triggers all-done when parent auto-closes",
        "all todo list items are now complete" in msg,
        f"got: {r!r}",
    )

    # all-done does NOT fire when other items remain open
    ad3: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "task 1"}, ad3
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "task 2"}, ad3
    )
    r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, ad3)
    msg = _j(r).get("message", "")
    cl.check(
        "no all-done with open items",
        "all-done does not fire when other items remain open",
        "all todo list items are now complete" not in msg,
        f"got: {r!r}",
    )
