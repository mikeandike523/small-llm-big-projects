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
        "todo_list", {"action": "list", "item_path": "1"}, env.session_data
    )
    sub_items = _j(r).get("items", [])
    cl.check(
        "list subtree count",
        "list(item_path='1') returns 2 children",
        len(sub_items) == 2,
        f"got: {r!r}",
    )
    cl.check(
        "list subtree paths",
        "Children have paths 1.1 and 1.2",
        [it["item_path"] for it in sub_items] == ["1.1", "1.2"],
        f"got: {sub_items!r}",
    )

    r = execute_tool(
        "todo_list", {"action": "list_formatted", "item_path": "1"}, env.session_data
    )
    cl.check(
        "list_formatted subtree has children",
        "Subtree formatted output shows children",
        "child A" in r and "child B" in r,
        f"got: {r!r}",
    )
    cl.check(
        "list_formatted subtree excludes sibling",
        "Subtree does not include sibling",
        "sibling" not in r,
        f"got: {r!r}",
    )
    cl.check(
        "list_formatted subtree paths",
        "Subtree shows 1.1. and 1.2. path notation",
        "1.1." in r and "1.2." in r,
        f"got: {r!r}",
    )
