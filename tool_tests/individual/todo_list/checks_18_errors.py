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
    err_s: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "item 1"}, err_s
    )

    # item_path doesn't exist
    r = execute_tool("todo_list", {"action": "get_item", "item_path": "99"}, err_s)
    d = _j(r)
    cl.check(
        "error item not found",
        "get_item with bad path returns error",
        "error" in d,
        f"got: {r!r}",
    )
    cl.check(
        "error item not found directive",
        "Error message is informative",
        "does not exist" in d.get("error", "") or "list" in d.get("error", "").lower(),
        f"got: {d.get('error')!r}",
    )

    # parent_path doesn't exist
    r = execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "5", "text": "x"}, err_s
    )
    d = _j(r)
    cl.check(
        "error parent not found",
        "add_item with bad parent_path returns error",
        "error" in d,
        f"got: {r!r}",
    )

    # before out of range
    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "before": 99, "text": "x"},
        err_s,
    )
    d = _j(r)
    cl.check(
        "error before out of range",
        "before out of range returns error",
        "error" in d,
        f"got: {r!r}",
    )
    cl.check(
        "error before directive",
        "before error mentions range",
        "out of range" in d.get("error", "") or "range" in d.get("error", ""),
        f"got: {d.get('error')!r}",
    )

    # after out of range
    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "after": 99, "text": "x"},
        err_s,
    )
    d = _j(r)
    cl.check(
        "error after out of range",
        "after out of range returns error",
        "error" in d,
        f"got: {r!r}",
    )

    # before and after both given
    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "before": 1, "after": 1, "text": "x"},
        err_s,
    )
    d = _j(r)
    cl.check(
        "error before and after",
        "Both before and after returns error",
        "error" in d,
        f"got: {r!r}",
    )
    cl.check(
        "error before and after directive",
        "Error mentions mutually exclusive",
        "mutually exclusive" in d.get("error", ""),
        f"got: {d.get('error')!r}",
    )

    # before on empty list
    empty_s: dict = {}
    r = execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "", "before": 1, "text": "x"},
        empty_s,
    )
    d = _j(r)
    cl.check(
        "error before empty list",
        "before on empty list returns error",
        "error" in d,
        f"got: {r!r}",
    )

    # Missing required args
    r = execute_tool("todo_list", {"action": "add_item"}, err_s)
    cl.check(
        "error add_item missing text",
        "add_item without text returns error",
        "error" in _j(r),
        f"got: {r!r}",
    )

    r = execute_tool(
        "todo_list", {"action": "add_many_items", "parent_path": ""}, err_s
    )
    cl.check(
        "error add_many_items missing texts",
        "add_many_items without texts returns error",
        "error" in _j(r),
        f"got: {r!r}",
    )

    r = execute_tool("todo_list", {"action": "get_item"}, err_s)
    cl.check(
        "error get_item missing path",
        "get_item without item_path returns error",
        "error" in _j(r),
        f"got: {r!r}",
    )

    r = execute_tool("todo_list", {"action": "update_item", "item_path": "1"}, err_s)
    cl.check(
        "error update_item missing text",
        "update_item without text returns error",
        "error" in _j(r),
        f"got: {r!r}",
    )

    # Navigate through leaf (no sub_list)
    nav_s: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "leaf"}, nav_s
    )
    r = execute_tool("todo_list", {"action": "get_item", "item_path": "1.1"}, nav_s)
    d = _j(r)
    cl.check(
        "error navigate through leaf",
        "Navigating through a leaf returns error",
        "error" in d,
        f"got: {r!r}",
    )
    cl.check(
        "error navigate directive",
        "Error mentions no children",
        "no children" in d.get("error", "").lower(),
        f"got: {d.get('error')!r}",
    )
