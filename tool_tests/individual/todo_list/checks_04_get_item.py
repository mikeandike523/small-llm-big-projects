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
        "todo_list", {"action": "get_item", "item_path": "1"}, env.session_data
    )
    cl.check(
        "get_item raw text",
        "get_item returns raw text 'step one'",
        r == "step one",
        f"got: {r!r}",
    )

    r = execute_tool(
        "todo_list", {"action": "get_item", "item_path": "2"}, env.session_data
    )
    cl.check(
        "get_item item 2",
        "get_item item 2 returns 'step two'",
        r == "step two",
        f"got: {r!r}",
    )
