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

        # get_all_formatted on empty list
        r_fmt_empty = execute_tool("todo_list", {"action": "get_all_formatted"}, env.session_data)
        cl.check("get_all_formatted empty", "Empty list returns '(empty todo list)'", r_fmt_empty == "(empty todo list)", f"got: {r_fmt_empty!r}")

        # add_item "step one" -> item_number=1
        r2 = execute_tool("todo_list", {"action": "add_item", "text": "step one"}, env.session_data)
        data2 = json.loads(r2)
        item2 = data2.get("item", {})
        cl.check("add_item first", "Adding first item returns item_number=1", item2.get("item_number") == 1, f"got: {r2!r}")
        cl.check("add_item first status", "Newly added item has status 'open'", item2.get("status") == "open", f"got: {r2!r}")

        # add_item "step two" -> item_number=2
        r3 = execute_tool("todo_list", {"action": "add_item", "text": "step two"}, env.session_data)
        data3 = json.loads(r3)
        item3 = data3.get("item", {})
        cl.check("add_item second", "Adding second item returns item_number=2", item3.get("item_number") == 2, f"got: {r3!r}")

        # get_all -> 2 items
        r4 = execute_tool("todo_list", {"action": "get_all"}, env.session_data)
        data4 = json.loads(r4)
        cl.check("get_all two items", "List has 2 items after adding two", len(data4.get("items", [])) == 2, f"got: {r4!r}")

        # get_all_formatted on non-empty list
        r_fmt = execute_tool("todo_list", {"action": "get_all_formatted"}, env.session_data)
        cl.check("get_all_formatted non-empty has items", "Formatted output contains both items", "step one" in r_fmt and "step two" in r_fmt, f"got: {r_fmt!r}")
        cl.check("get_all_formatted checkboxes", "Formatted output uses [ ] for open items", "[ ]" in r_fmt, f"got: {r_fmt!r}")

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

        # get_all_formatted after close -> closed item shows [x]
        r_fmt2 = execute_tool("todo_list", {"action": "get_all_formatted"}, env.session_data)
        cl.check("get_all_formatted closed item", "Closed item shows [x] checkbox", "[x]" in r_fmt2, f"got: {r_fmt2!r}")

        # reopen_item item_number=1 -> status back to "open"
        r_reopen = execute_tool("todo_list", {"action": "reopen_item", "item_number": 1}, env.session_data)
        data_reopen = json.loads(r_reopen)
        cl.check("reopen_item", "Reopened item has status 'open'", data_reopen.get("item", {}).get("status") == "open", f"got: {r_reopen!r}")

        # delete_item item_number=2 -> list has 1 item
        execute_tool("todo_list", {"action": "delete_item", "item_number": 2}, env.session_data)
        r8 = execute_tool("todo_list", {"action": "get_all"}, env.session_data)
        data8 = json.loads(r8)
        cl.check("delete_item leaves one", "List has 1 item after deleting item 2", len(data8.get("items", [])) == 1, f"got: {r8!r}")

        # add_multiple_items
        r_multi = execute_tool("todo_list", {"action": "add_multiple_items", "texts": ["alpha", "beta", "gamma"]}, env.session_data)
        data_multi = json.loads(r_multi)
        cl.check("add_multiple_items count", "add_multiple_items returns 3 items", len(data_multi.get("items", [])) == 3, f"got: {r_multi!r}")
        cl.check("add_multiple_items message", "add_multiple_items message mentions 3 items", "3" in data_multi.get("message", ""), f"got: {r_multi!r}")
        r_all_multi = execute_tool("todo_list", {"action": "get_all"}, env.session_data)
        data_all_multi = json.loads(r_all_multi)
        cl.check("add_multiple_items total", "Total list has 4 items after adding 3 more", len(data_all_multi.get("items", [])) == 4, f"got: {r_all_multi!r}")

        # insert_before item_number=2 -> inserts at position 2, shifts rest
        r_ins_before = execute_tool("todo_list", {"action": "insert_before", "item_number": 2, "text": "inserted before 2"}, env.session_data)
        data_ins_before = json.loads(r_ins_before)
        cl.check("insert_before item_number", "insert_before returns item_number=2", data_ins_before.get("item", {}).get("item_number") == 2, f"got: {r_ins_before!r}")
        r_check_before = execute_tool("todo_list", {"action": "get_item", "item_number": 2}, env.session_data)
        data_check_before = json.loads(r_check_before)
        cl.check("insert_before text", "Item at position 2 is now the inserted item", data_check_before.get("item", {}).get("text") == "inserted before 2", f"got: {r_check_before!r}")

        # insert_after item_number=1 -> new item at position 2
        r_ins_after = execute_tool("todo_list", {"action": "insert_after", "item_number": 1, "text": "inserted after 1"}, env.session_data)
        data_ins_after = json.loads(r_ins_after)
        cl.check("insert_after item_number", "insert_after returns item_number=2", data_ins_after.get("item", {}).get("item_number") == 2, f"got: {r_ins_after!r}")
        r_check_after = execute_tool("todo_list", {"action": "get_item", "item_number": 2}, env.session_data)
        data_check_after = json.loads(r_check_after)
        cl.check("insert_after text", "Item at position 2 is the inserted-after item", data_check_after.get("item", {}).get("text") == "inserted after 1", f"got: {r_check_after!r}")

        # auto_strip_leading_numbers (default True) strips "1. " prefix
        r_strip = execute_tool("todo_list", {"action": "add_item", "text": "1. numbered item"}, env.session_data)
        data_strip = json.loads(r_strip)
        cl.check("auto_strip leading number", "Leading '1. ' stripped from item text", data_strip.get("item", {}).get("text") == "numbered item", f"got: {r_strip!r}")

        # auto_strip_leading_numbers=False preserves "2) " prefix
        r_no_strip = execute_tool("todo_list", {"action": "add_item", "text": "2) keep prefix", "auto_strip_leading_numbers": False}, env.session_data)
        data_no_strip = json.loads(r_no_strip)
        cl.check("no auto_strip preserves prefix", "Prefix '2) ' preserved when auto_strip=False", data_no_strip.get("item", {}).get("text") == "2) keep prefix", f"got: {r_no_strip!r}")

        # auto_strip_leading_numbers with add_multiple_items
        r_strip_multi = execute_tool("todo_list", {"action": "add_multiple_items", "texts": ["1. first", "2. second"]}, env.session_data)
        data_strip_multi = json.loads(r_strip_multi)
        stripped_texts = [it["text"] for it in data_strip_multi.get("items", [])]
        cl.check("auto_strip in add_multiple_items", "Leading numbers stripped from all texts in add_multiple_items", stripped_texts == ["first", "second"], f"got: {stripped_texts!r}")

        # --- Error cases ---

        # get_item out of range
        r_oob = execute_tool("todo_list", {"action": "get_item", "item_number": 9999}, env.session_data)
        data_oob = json.loads(r_oob)
        cl.check("get_item out of range", "get_item with out-of-range number returns error", "error" in data_oob, f"got: {r_oob!r}")

        # get_item requires item_number
        r_no_num = execute_tool("todo_list", {"action": "get_item"}, env.session_data)
        data_no_num = json.loads(r_no_num)
        cl.check("get_item missing item_number", "get_item without item_number returns error", "error" in data_no_num, f"got: {r_no_num!r}")

        # add_item requires text
        r_no_text = execute_tool("todo_list", {"action": "add_item"}, env.session_data)
        data_no_text = json.loads(r_no_text)
        cl.check("add_item missing text", "add_item without text returns error", "error" in data_no_text, f"got: {r_no_text!r}")

        # add_multiple_items requires texts
        r_no_texts = execute_tool("todo_list", {"action": "add_multiple_items"}, env.session_data)
        data_no_texts = json.loads(r_no_texts)
        cl.check("add_multiple_items missing texts", "add_multiple_items without texts returns error", "error" in data_no_texts, f"got: {r_no_texts!r}")

        # delete_item out of range
        r_del_oob = execute_tool("todo_list", {"action": "delete_item", "item_number": 9999}, env.session_data)
        data_del_oob = json.loads(r_del_oob)
        cl.check("delete_item out of range", "delete_item with out-of-range number returns error", "error" in data_del_oob, f"got: {r_del_oob!r}")

        # unknown action: schema enum validation fires before execute(), so result is a plain error string
        r_unknown = execute_tool("todo_list", {"action": "unknown_action"}, env.session_data)
        cl.check("unknown action", "Unknown action returns an error string", "Failed" in r_unknown or "error" in r_unknown.lower(), f"got: {r_unknown!r}")

        # close_item all-done message: use a fresh session for isolation
        fresh_session: dict = {}
        execute_tool("todo_list", {"action": "add_item", "text": "only task"}, fresh_session)
        r_all_done = execute_tool("todo_list", {"action": "close_item", "item_number": 1}, fresh_session)
        data_all_done = json.loads(r_all_done)
        msg_all_done = data_all_done.get("message", "")
        cl.check("close_item all done message", "Closing last open item includes all-completed note", "all todo list items completed" in msg_all_done, f"got: {r_all_done!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
