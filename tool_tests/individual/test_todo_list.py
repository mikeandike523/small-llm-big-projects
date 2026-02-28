from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("todo_list")
    try:
        # get_all on empty list
        r = execute_tool("todo_list", {"action": "get_all"}, env.session_data)
        data = json.loads(r)
        cl.check("get_all empty", "Empty list returns items=[]", data.get("items") == [], f"got: {r!r}")

        # add_item "step one" -> item_number=1
        r2 = execute_tool("todo_list", {"action": "add_item", "text": "step one"}, env.session_data)
        data2 = json.loads(r2)
        item2 = data2.get("item", {})
        cl.check("add_item first", "Adding first item returns item_number=1", item2.get("item_number") == 1, f"got: {r2!r}")

        # add_item "step two" -> item_number=2
        r3 = execute_tool("todo_list", {"action": "add_item", "text": "step two"}, env.session_data)
        data3 = json.loads(r3)
        item3 = data3.get("item", {})
        cl.check("add_item second", "Adding second item returns item_number=2", item3.get("item_number") == 2, f"got: {r3!r}")

        # get_all -> 2 items
        r4 = execute_tool("todo_list", {"action": "get_all"}, env.session_data)
        data4 = json.loads(r4)
        cl.check("get_all two items", "List has 2 items after adding two", len(data4.get("items", [])) == 2, f"got: {r4!r}")

        # get_item item_number=1 -> text="step one"
        r5 = execute_tool("todo_list", {"action": "get_item", "item_number": 1}, env.session_data)
        data5 = json.loads(r5)
        cl.check("get_item 1 text", "Item 1 has text 'step one'", data5.get("item", {}).get("text") == "step one", f"got: {r5!r}")

        # modify_item item_number=1, text="step ONE"
        r6 = execute_tool("todo_list", {"action": "modify_item", "item_number": 1, "text": "step ONE"}, env.session_data)
        data6 = json.loads(r6)
        cl.check("modify_item", "Modify updates item text", data6.get("item", {}).get("text") == "step ONE", f"got: {r6!r}")

        # close_item item_number=1 -> status "closed"
        r7 = execute_tool("todo_list", {"action": "close_item", "item_number": 1}, env.session_data)
        data7 = json.loads(r7)
        cl.check("close_item status", "Closed item has status 'closed'", data7.get("item", {}).get("status") == "closed", f"got: {r7!r}")

        # delete_item item_number=2 -> list has 1 item
        execute_tool("todo_list", {"action": "delete_item", "item_number": 2}, env.session_data)
        r8 = execute_tool("todo_list", {"action": "get_all"}, env.session_data)
        data8 = json.loads(r8)
        cl.check("delete_item leaves one", "List has 1 item after deleting item 2", len(data8.get("items", [])) == 1, f"got: {r8!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
