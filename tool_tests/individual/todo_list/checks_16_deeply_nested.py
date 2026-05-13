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
    gn: dict = {}
    execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "root"}, gn)
    execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child"}, gn)
    execute_tool("todo_list", {"action": "add_item", "parent_path": "1.1", "text": "grandchild"}, gn)

    r = execute_tool("todo_list", {"action": "get_item", "item_path": "1.1.1"}, gn)
    cl.check("grandchild get_item", "Grandchild text is 'grandchild'",
             r == "grandchild", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "list_formatted"}, gn)
    cl.check("grandchild in formatted tree", "Full tree shows grandchild at path 1.1.1.",
             "1.1.1." in r, f"got: {r!r}")

