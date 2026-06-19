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


def _seed(texts: list[str], parent: str = "") -> dict:
    sd: dict = {}
    execute_tool(
        "todo_list",
        {"action": "add_many_items", "parent_path": parent, "texts": texts},
        sd,
    )
    return sd


def add_checks(cl: CheckList, env: TestEnv) -> None:
    # Basic multi-delete with non-contiguous paths and index shifting.
    sd = _seed(["a", "b", "c", "d"])
    r = execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["1", "3"]}, sd
    )
    d = _j(r)
    remaining = [
        it["text"]
        for it in _j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", [])
    ]
    cl.check(
        "delete_many basic",
        "Deleting 1 and 3 from [a,b,c,d] leaves [b,d]",
        len(d.get("deleted", [])) == 2 and remaining == ["b", "d"],
        f"got: {r!r} remaining={remaining!r}",
    )

    # Missing item_paths is an error.
    r = execute_tool("todo_list", {"action": "delete_many_items"}, _seed(["a"]))
    cl.check(
        "delete_many requires item_paths",
        "delete_many_items without item_paths errors",
        "error" in _j(r),
        f"got: {r!r}",
    )

    # Paths under different parents are rejected and nothing is deleted.
    sd = _seed(["p", "q"])
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "child"}, sd
    )  # promotes item 1
    r = execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["1.1", "2"]}, sd
    )
    count = len(_j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", []))
    cl.check(
        "delete_many same-parent enforced",
        "Mixed-parent paths error and delete nothing",
        "error" in _j(r) and count == 2,
        f"got: {r!r} count={count}",
    )

    # Duplicate path in the same call is rejected.
    sd = _seed(["a", "b", "c"])
    r = execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["2", "2"]}, sd
    )
    count = len(_j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", []))
    cl.check(
        "delete_many duplicate rejected",
        "Duplicate item_path errors and deletes nothing",
        "error" in _j(r) and count == 3,
        f"got: {r!r} count={count}",
    )

    # A non-existent path makes the whole call fail atomically.
    sd = _seed(["a", "b"])
    r = execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["1", "9"]}, sd
    )
    count = len(_j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", []))
    cl.check(
        "delete_many atomic on bad path",
        "An invalid path leaves the list untouched",
        "error" in _j(r) and count == 2,
        f"got: {r!r} count={count}",
    )

    # Promoted item without cascade errors and deletes nothing.
    sd = _seed(["a", "b"])
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "kid"}, sd
    )  # promote item 1
    r = execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["1", "2"]}, sd
    )
    count = len(_j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", []))
    cl.check(
        "delete_many cascade guard",
        "Promoted item without cascade errors, nothing deleted",
        "error" in _j(r) and count == 2,
        f"got: {r!r} count={count}",
    )

    # cascade_delete=true removes a promoted item and its descendants.
    sd = _seed(["a", "b"])
    execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "1", "text": "kid"}, sd
    )
    r = execute_tool(
        "todo_list",
        {"action": "delete_many_items", "item_paths": ["1", "2"], "cascade_delete": True},
        sd,
    )
    count = len(_j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", []))
    cl.check(
        "delete_many cascade deletes",
        "cascade_delete=true removes promoted item and leaves empty list",
        "error" not in _j(r) and count == 0,
        f"got: {r!r} count={count}",
    )

    # Deleting all children of a promoted parent demotes it back to a leaf.
    sd = _seed(["parent"])
    execute_tool(
        "todo_list",
        {"action": "add_many_items", "parent_path": "1", "texts": ["x", "y"]},
        sd,
    )
    execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["1.1", "1.2"]}, sd
    )
    items = _j(execute_tool("todo_list", {"action": "list"}, sd)).get("items", [])
    cl.check(
        "delete_many demotes emptied parent",
        "Deleting all children demotes the parent to a leaf",
        len(items) == 1 and "children" not in items[0],
        f"got: {items!r}",
    )

    # Result includes the structure-change reminder.
    sd = _seed(["a", "b"])
    r = execute_tool(
        "todo_list", {"action": "delete_many_items", "item_paths": ["1"]}, sd
    )
    cl.check(
        "delete_many reminder",
        "delete_many_items appends the resulting-list reminder",
        "<system-reminder>" in r and "[ ] 1. b" in r,
        f"got: {r!r}",
    )
