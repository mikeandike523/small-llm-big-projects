from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("todo_list")
    try:
        # ----------------------------------------------------------------
        # Basic root-level operations
        # ----------------------------------------------------------------

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

        # ----------------------------------------------------------------
        # Error cases
        # ----------------------------------------------------------------

        r_oob = execute_tool("todo_list", {"action": "get_item", "item_number": 9999}, env.session_data)
        data_oob = json.loads(r_oob)
        cl.check("get_item out of range", "get_item with out-of-range number returns error", "error" in data_oob, f"got: {r_oob!r}")

        r_no_num = execute_tool("todo_list", {"action": "get_item"}, env.session_data)
        data_no_num = json.loads(r_no_num)
        cl.check("get_item missing item_number", "get_item without item_number returns error", "error" in data_no_num, f"got: {r_no_num!r}")

        r_no_text = execute_tool("todo_list", {"action": "add_item"}, env.session_data)
        data_no_text = json.loads(r_no_text)
        cl.check("add_item missing text", "add_item without text returns error", "error" in data_no_text, f"got: {r_no_text!r}")

        r_no_texts = execute_tool("todo_list", {"action": "add_multiple_items"}, env.session_data)
        data_no_texts = json.loads(r_no_texts)
        cl.check("add_multiple_items missing texts", "add_multiple_items without texts returns error", "error" in data_no_texts, f"got: {r_no_texts!r}")

        r_del_oob = execute_tool("todo_list", {"action": "delete_item", "item_number": 9999}, env.session_data)
        data_del_oob = json.loads(r_del_oob)
        cl.check("delete_item out of range", "delete_item with out-of-range number returns error", "error" in data_del_oob, f"got: {r_del_oob!r}")

        r_unknown = execute_tool("todo_list", {"action": "unknown_action"}, env.session_data)
        cl.check("unknown action", "Unknown action returns an error string", "Failed" in r_unknown or "error" in r_unknown.lower(), f"got: {r_unknown!r}")

        # close_item all-done message
        fresh_session: dict = {}
        execute_tool("todo_list", {"action": "add_item", "text": "only task"}, fresh_session)
        r_all_done = execute_tool("todo_list", {"action": "close_item", "item_number": 1}, fresh_session)
        data_all_done = json.loads(r_all_done)
        msg_all_done = data_all_done.get("message", "")
        cl.check("close_item all done message", "Closing last open item includes all-completed note", "all todo list items completed" in msg_all_done, f"got: {r_all_done!r}")

        # ----------------------------------------------------------------
        # Hierarchical: sub_list_path operations
        # ----------------------------------------------------------------

        hs: dict = {}  # fresh session for hierarchy tests
        execute_tool("todo_list", {"action": "add_item", "text": "Root 1"}, hs)
        execute_tool("todo_list", {"action": "add_item", "text": "Root 2"}, hs)

        # add to sub-list of item 1
        execute_tool("todo_list", {"action": "add_item", "text": "Child A", "sub_list_path": "1"}, hs)
        execute_tool("todo_list", {"action": "add_item", "text": "Child B", "sub_list_path": "1"}, hs)
        r_sub_all = execute_tool("todo_list", {"action": "get_all", "sub_list_path": "1"}, hs)
        data_sub_all = json.loads(r_sub_all)
        sub_items = data_sub_all.get("items", [])
        cl.check("sub_list add_item count", "sub-list of item 1 has 2 children", len(sub_items) == 2, f"got: {r_sub_all!r}")
        cl.check("sub_list add_item text", "First child has correct text", sub_items[0].get("text") == "Child A", f"got: {sub_items!r}")

        # get_all at root includes sub_list in JSON
        r_root_all = execute_tool("todo_list", {"action": "get_all"}, hs)
        data_root_all = json.loads(r_root_all)
        root_item_1 = data_root_all["items"][0]
        cl.check("get_all root includes sub_list", "Root get_all includes sub_list on item 1", "sub_list" in root_item_1, f"got: {root_item_1!r}")
        cl.check("get_all root sub_list length", "sub_list on item 1 has 2 entries", len(root_item_1.get("sub_list", [])) == 2, f"got: {root_item_1!r}")

        # get_all_formatted shows hierarchical paths
        r_fmt_hier = execute_tool("todo_list", {"action": "get_all_formatted"}, hs)
        cl.check("get_all_formatted hierarchical paths", "Formatted output uses path notation like '1.1.'", "1.1." in r_fmt_hier, f"got: {r_fmt_hier!r}")
        cl.check("get_all_formatted root items present", "Formatted output shows root items", "Root 1" in r_fmt_hier and "Root 2" in r_fmt_hier, f"got: {r_fmt_hier!r}")

        # get_all_formatted with sub_list_path shows subtree with full path prefix
        r_fmt_sub = execute_tool("todo_list", {"action": "get_all_formatted", "sub_list_path": "1"}, hs)
        cl.check("get_all_formatted subtree prefix", "Subtree formatted with correct path prefix '1.1.'", "1.1." in r_fmt_sub, f"got: {r_fmt_sub!r}")
        cl.check("get_all_formatted subtree excludes root", "Subtree view does not include Root 2", "Root 2" not in r_fmt_sub, f"got: {r_fmt_sub!r}")

        # close a sub-item
        execute_tool("todo_list", {"action": "close_item", "item_number": 1, "sub_list_path": "1"}, hs)
        r_sub_item = execute_tool("todo_list", {"action": "get_item", "item_number": 1, "sub_list_path": "1"}, hs)
        data_sub_item = json.loads(r_sub_item)
        cl.check("sub_list close_item", "Closed sub-item has status 'closed'", data_sub_item.get("item", {}).get("status") == "closed", f"got: {r_sub_item!r}")

        # closing sub-item should NOT trigger all-done (root item 2 still open)
        cl.check("sub_list close_item no all-done", "Closing sub-item does not trigger all-done when root items remain open",
                 "all todo list items completed" not in json.loads(
                     execute_tool("todo_list", {"action": "close_item", "item_number": 2, "sub_list_path": "1"}, hs)
                 ).get("message", ""), "unexpected all-done message")

        # deeply nested: grandchild
        execute_tool("todo_list", {"action": "add_item", "text": "Grandchild", "sub_list_path": "1.1"}, hs)
        r_grand = execute_tool("todo_list", {"action": "get_all", "sub_list_path": "1.1"}, hs)
        data_grand = json.loads(r_grand)
        cl.check("grandchild add", "Grandchild added at depth 2", len(data_grand.get("items", [])) == 1, f"got: {r_grand!r}")
        cl.check("grandchild text", "Grandchild has correct text", data_grand["items"][0].get("text") == "Grandchild", f"got: {r_grand!r}")

        # grandchild visible in full formatted tree
        r_fmt_full = execute_tool("todo_list", {"action": "get_all_formatted"}, hs)
        cl.check("grandchild in full tree", "Full formatted tree shows grandchild at path 1.1.1.", "1.1.1." in r_fmt_full, f"got: {r_fmt_full!r}")

        # invalid sub_list_path returns error
        r_bad_path = execute_tool("todo_list", {"action": "add_item", "text": "X", "sub_list_path": "99"}, hs)
        data_bad_path = json.loads(r_bad_path)
        cl.check("invalid sub_list_path error", "Out-of-range sub_list_path returns error", "error" in data_bad_path, f"got: {r_bad_path!r}")

        r_bad_seg = execute_tool("todo_list", {"action": "add_item", "text": "X", "sub_list_path": "abc"}, hs)
        data_bad_seg = json.loads(r_bad_seg)
        cl.check("non-integer sub_list_path error", "Non-integer sub_list_path segment returns error", "error" in data_bad_seg, f"got: {r_bad_seg!r}")

        # delete sub-item
        execute_tool("todo_list", {"action": "add_item", "text": "Extra Child", "sub_list_path": "2"}, hs)
        execute_tool("todo_list", {"action": "delete_item", "item_number": 1, "sub_list_path": "2"}, hs)
        r_sub2 = execute_tool("todo_list", {"action": "get_all", "sub_list_path": "2"}, hs)
        data_sub2 = json.loads(r_sub2)
        cl.check("sub_list delete_item", "Deleted sub-item leaves empty sub-list", len(data_sub2.get("items", [])) == 0, f"got: {r_sub2!r}")

        # all-done triggers when ALL items (recursively) are closed
        done_session: dict = {}
        execute_tool("todo_list", {"action": "add_item", "text": "Parent task"}, done_session)
        execute_tool("todo_list", {"action": "add_item", "text": "Sub task", "sub_list_path": "1"}, done_session)
        execute_tool("todo_list", {"action": "close_item", "item_number": 1, "sub_list_path": "1"}, done_session)
        r_done = execute_tool("todo_list", {"action": "close_item", "item_number": 1}, done_session)
        data_done = json.loads(r_done)
        cl.check("all_closed recursive triggers message", "all-done message fires when root and sub-items all closed",
                 "all todo list items completed" in data_done.get("message", ""), f"got: {r_done!r}")

        # all-done does NOT trigger when a sub-item is still open
        partial_session: dict = {}
        execute_tool("todo_list", {"action": "add_item", "text": "Parent"}, partial_session)
        execute_tool("todo_list", {"action": "add_item", "text": "Open sub", "sub_list_path": "1"}, partial_session)
        r_partial = execute_tool("todo_list", {"action": "close_item", "item_number": 1}, partial_session)
        data_partial = json.loads(r_partial)
        cl.check("all_closed recursive no trigger with open sub", "all-done does not fire when a sub-item is still open",
                 "all todo list items completed" not in data_partial.get("message", ""), f"got: {r_partial!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
