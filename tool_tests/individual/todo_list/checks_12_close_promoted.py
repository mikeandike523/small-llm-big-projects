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
        "close_item promoted error",
        "close_item on promoted item returns error",
        "error" in d,
        f"got: {r!r}",
    )
    cl.check(
        "close_item promoted directive",
        "Error message is informative about auto-close",
        "children" in d.get("error", "").lower()
        or "sub-list" in d.get("error", "").lower(),
        f"got: {d.get('error')!r}",
    )

    r = execute_tool(
        "todo_list", {"action": "reopen_item", "item_path": "1"}, env.session_data
    )
    d = _j(r)
    cl.check(
        "reopen_item promoted error",
        "reopen_item on promoted item returns error",
        "error" in d,
        f"got: {r!r}",
    )
