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
    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "text": "step one"},
        env.session_data,
    )
    d = _j(r)
    cl.check(
        "add_item first path",
        "First item has item_path='1'",
        d.get("item_path") == "1",
        f"got: {r!r}",
    )

    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "text": "step two"},
        env.session_data,
    )
    d = _j(r)
    cl.check(
        "add_item second path",
        "Second item has item_path='2'",
        d.get("item_path") == "2",
        f"got: {r!r}",
    )

    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "text": "step three"},
        env.session_data,
    )
    cl.check(
        "add_item third path",
        "Third item has item_path='3'",
        _j(r).get("item_path") == "3",
        f"got: {r!r}",
    )
