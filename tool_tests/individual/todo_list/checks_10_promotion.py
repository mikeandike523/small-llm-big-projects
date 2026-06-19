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
    # Clear any todo list state from previous checks so this group starts fresh.
    env.session_data.pop("todo_list", None)
    execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "text": "parent task"},
        env.session_data,
    )
    execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "text": "sibling"},
        env.session_data,
    )

    # Promote item 1 by adding a child
    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "1", "text": "child A"},
        env.session_data,
    )
    d = _j(r)
    cl.check(
        "promotion child path",
        "First child of promoted item has path '1.1'",
        d.get("item_path") == "1.1",
        f"got: {r!r}",
    )

    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "1", "text": "child B"},
        env.session_data,
    )
    cl.check(
        "promotion second child path",
        "Second child has path '1.2'",
        _j(r).get("item_path") == "1.2",
        f"got: {r!r}",
    )

    # Item 1 text unchanged after promotion
    r = execute_tool(
        "todo_list", {"action": "get_item", "item_path": "1"}, env.session_data
    )
    cl.check(
        "promotion text preserved",
        "Promoted item keeps its original text",
        r == "parent task",
        f"got: {r!r}",
    )

    # update_item on promoted item (renames the group)
    r = execute_tool(
        "todo_list",
        {"action": "update_item", "item_path": "1", "text": "renamed group"},
        env.session_data,
    )
    cl.check(
        "update promoted item",
        "update_item works on promoted item",
        _j(r).get("text") == "renamed group",
        f"got: {r!r}",
    )
