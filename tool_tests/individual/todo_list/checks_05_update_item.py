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
    r = execute_tool("todo_list", {"action": "update_item", "item_path": "1", "text": "step ONE"}, env.session_data)
    cl.check("update_item success", "update_item returns updated text",
             _j(r).get("text") == "step ONE", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "get_item", "item_path": "1"}, env.session_data)
    cl.check("update_item persisted", "Updated text persists via get_item",
             r == "step ONE", f"got: {r!r}")

