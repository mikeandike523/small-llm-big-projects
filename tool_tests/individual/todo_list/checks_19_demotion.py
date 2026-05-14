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
    dm: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm
    )
    execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "1", "text": "only child"},
        dm,
    )

    # Item 1 is now promoted; delete its only child
    execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm)

    # Item 1 should now be a plain leaf (no children)
    r = execute_tool("todo_list", {"action": "list"}, dm)
    items = _j(r).get("items", [])
    cl.check(
        "demotion leaf after last child deleted",
        "Item is demoted to leaf after last child deleted",
        len(items) == 1 and "children" not in items[0],
        f"got: {items!r}",
    )

    # Should be closeable again as a leaf
    r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, dm)
    cl.check(
        "demotion leaf closeable",
        "Demoted item can be closed as a leaf",
        "error" not in _j(r),
        f"got: {r!r}",
    )

    # Captured status: delete a closed-last-child → item demotes as closed
    dm2: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm2
    )
    execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "1", "text": "only child"},
        dm2,
    )
    execute_tool("todo_list", {"action": "close_item", "item_path": "1.1"}, dm2)
    execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm2)
    r = execute_tool("todo_list", {"action": "list"}, dm2)
    items = _j(r).get("items", [])
    cl.check(
        "demotion captures closed status",
        "Demoted item captures 'closed' when last child was closed",
        items[0].get("status") == "closed",
        f"got: {items!r}",
    )

    # Captured status: delete an open-last-child → item demotes as open
    dm3: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm3
    )
    execute_tool(
        "todo_list",
        {"action": "add_item", "parent_path": "1", "text": "only child"},
        dm3,
    )
    # child remains open; delete it
    execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm3)
    r = execute_tool("todo_list", {"action": "list"}, dm3)
    items = _j(r).get("items", [])
    cl.check(
        "demotion captures open status",
        "Demoted item captures 'open' when last child was open",
        items[0].get("status") == "open",
        f"got: {items!r}",
    )

    # Deleting a non-last child does NOT demote
    dm4: dict = {}
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm4
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child A"}, dm4
    )
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child B"}, dm4
    )
    execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm4)
    r = execute_tool("todo_list", {"action": "list"}, dm4)
    items = _j(r).get("items", [])
    cl.check(
        "no demotion with remaining child",
        "Item not demoted when children remain after delete",
        items[0].get("children") is not None,
        f"got: {items!r}",
    )

    # Unknown action (schema validation rejects removed actions before execution)
    r = execute_tool("todo_list", {"action": "get_all"}, {})
    cl.check(
        "unknown action",
        "Old action 'get_all' is rejected",
        "error" in _j(r) or "fail" in r.lower() or "error" in r.lower(),
        f"got: {r!r}",
    )
