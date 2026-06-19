from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool

_MARKER = "<system-reminder>"


def _j(r: str) -> dict:
    marker = "\n\n<system-reminder>"
    if marker in r:
        r = r.split(marker, 1)[0]
    try:
        return json.loads(r)
    except Exception:
        return {}


def add_checks(cl: CheckList, env: TestEnv) -> None:
    sd: dict = {}

    # add_item appends a reminder showing the resulting list.
    r = execute_tool(
        "todo_list", {"action": "add_item", "parent_path": "", "text": "one"}, sd
    )
    cl.check(
        "reminder on add_item",
        "add_item appends the resulting-list reminder",
        _MARKER in r and "[ ] 1. one" in r,
        f"got: {r!r}",
    )

    # add_many_items appends a reminder.
    r = execute_tool(
        "todo_list",
        {"action": "add_many_items", "parent_path": "", "texts": ["two", "three"]},
        sd,
    )
    cl.check(
        "reminder on add_many_items",
        "add_many_items appends the resulting-list reminder",
        _MARKER in r and "[ ] 3. three" in r,
        f"got: {r!r}",
    )

    # delete_item appends a reminder.
    r = execute_tool("todo_list", {"action": "delete_item", "item_path": "3"}, sd)
    reminder = r.split("\n\n" + _MARKER, 1)[1] if _MARKER in r else ""
    cl.check(
        "reminder on delete_item",
        "delete_item appends the resulting-list reminder without the deleted item",
        _MARKER in r and "three" not in reminder and "[ ] 2. two" in reminder,
        f"got: {r!r}",
    )

    # update_item changes text only (not structure) -> NO reminder.
    r = execute_tool(
        "todo_list", {"action": "update_item", "item_path": "1", "text": "one!"}, sd
    )
    cl.check(
        "no reminder on update_item",
        "update_item does not append a reminder",
        _MARKER not in r,
        f"got: {r!r}",
    )

    # close_item is status-only -> NO reminder.
    r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, sd)
    cl.check(
        "no reminder on close_item",
        "close_item does not append a reminder",
        _MARKER not in r,
        f"got: {r!r}",
    )

    # reopen_item is status-only -> NO reminder.
    r = execute_tool("todo_list", {"action": "reopen_item", "item_path": "1"}, sd)
    cl.check(
        "no reminder on reopen_item",
        "reopen_item does not append a reminder",
        _MARKER not in r,
        f"got: {r!r}",
    )

    # close_many_items is status-only -> NO reminder.
    r = execute_tool(
        "todo_list", {"action": "close_many_items", "item_paths": ["1"]}, sd
    )
    cl.check(
        "no reminder on close_many_items",
        "close_many_items does not append a reminder",
        _MARKER not in r,
        f"got: {r!r}",
    )

    # list / list_formatted / get_item are read-only -> NO reminder.
    r_list = execute_tool("todo_list", {"action": "list"}, sd)
    r_fmt = execute_tool("todo_list", {"action": "list_formatted"}, sd)
    cl.check(
        "no reminder on reads",
        "Read-only actions do not append a reminder",
        _MARKER not in r_list and _MARKER not in r_fmt,
        f"got list={r_list!r} fmt={r_fmt!r}",
    )

    # clear appends a reminder showing the now-empty list.
    r = execute_tool("todo_list", {"action": "clear"}, sd)
    cl.check(
        "reminder on clear",
        "clear appends the resulting-list reminder (empty list)",
        _MARKER in r and "(empty todo list)" in r,
        f"got: {r!r}",
    )
