from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def _j(r: str) -> dict:
    """Parse JSON result, return empty dict on failure."""
    try:
        return json.loads(r)
    except Exception:
        return {}


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("todo_list")
    try:
        # ----------------------------------------------------------------
        # list / list_formatted — empty
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "list"}, env.session_data)
        cl.check("list empty", "Empty list returns items=[]",
                 _j(r).get("items") == [], f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "list_formatted"}, env.session_data)
        cl.check("list_formatted empty", "Empty list returns '(empty todo list)'",
                 r == "(empty todo list)", f"got: {r!r}")

        # ----------------------------------------------------------------
        # add_item to root
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "step one"}, env.session_data)
        d = _j(r)
        cl.check("add_item first path", "First item has item_path='1'",
                 d.get("item_path") == "1", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "step two"}, env.session_data)
        d = _j(r)
        cl.check("add_item second path", "Second item has item_path='2'",
                 d.get("item_path") == "2", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "step three"}, env.session_data)
        cl.check("add_item third path", "Third item has item_path='3'",
                 _j(r).get("item_path") == "3", f"got: {r!r}")

        # ----------------------------------------------------------------
        # list / list_formatted — non-empty
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "list"}, env.session_data)
        items = _j(r).get("items", [])
        cl.check("list three items count", "list returns 3 items", len(items) == 3, f"got: {r!r}")
        cl.check("list item_path field", "Items have item_path field",
                 items[0].get("item_path") == "1" and items[2].get("item_path") == "3",
                 f"got: {items!r}")
        cl.check("list status open", "Newly added items have status 'open'",
                 all(it.get("status") == "open" for it in items), f"got: {items!r}")

        r = execute_tool("todo_list", {"action": "list_formatted"}, env.session_data)
        cl.check("list_formatted has items", "Formatted output contains both items",
                 "step one" in r and "step two" in r, f"got: {r!r}")
        cl.check("list_formatted checkboxes", "Formatted output uses [ ] for open items",
                 "[ ]" in r, f"got: {r!r}")
        cl.check("list_formatted path notation", "Formatted output uses dot-path notation",
                 "1." in r and "2." in r, f"got: {r!r}")

        # ----------------------------------------------------------------
        # get_item — returns raw text, not JSON
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "get_item", "item_path": "1"}, env.session_data)
        cl.check("get_item raw text", "get_item returns raw text 'step one'",
                 r == "step one", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "get_item", "item_path": "2"}, env.session_data)
        cl.check("get_item item 2", "get_item item 2 returns 'step two'",
                 r == "step two", f"got: {r!r}")

        # ----------------------------------------------------------------
        # update_item
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "update_item", "item_path": "1", "text": "step ONE"}, env.session_data)
        cl.check("update_item success", "update_item returns updated text",
                 _j(r).get("text") == "step ONE", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "get_item", "item_path": "1"}, env.session_data)
        cl.check("update_item persisted", "Updated text persists via get_item",
                 r == "step ONE", f"got: {r!r}")

        # ----------------------------------------------------------------
        # close_item / reopen_item — leaf
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, env.session_data)
        d = _j(r)
        cl.check("close_item status", "close_item returns status='closed'",
                 d.get("status") == "closed", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "list"}, env.session_data)
        items = _j(r).get("items", [])
        cl.check("close_item reflected in list", "Closed item shows status='closed' in list",
                 items[0].get("status") == "closed", f"got: {items!r}")

        r = execute_tool("todo_list", {"action": "list_formatted"}, env.session_data)
        cl.check("list_formatted closed checkbox", "Closed item shows [x] in formatted output",
                 "[x]" in r, f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "reopen_item", "item_path": "1"}, env.session_data)
        cl.check("reopen_item status", "reopen_item returns status='open'",
                 _j(r).get("status") == "open", f"got: {r!r}")

        # ----------------------------------------------------------------
        # delete_item — leaf
        # ----------------------------------------------------------------

        execute_tool("todo_list", {"action": "delete_item", "item_path": "3"}, env.session_data)
        r = execute_tool("todo_list", {"action": "list"}, env.session_data)
        items = _j(r).get("items", [])
        cl.check("delete_item leaf", "List has 2 items after deleting item 3",
                 len(items) == 2, f"got: {r!r}")

        # ----------------------------------------------------------------
        # add_item with before / after
        # ----------------------------------------------------------------

        # list is now: 1=step ONE, 2=step two
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "before": 2, "text": "inserted before 2"}, env.session_data)
        d = _j(r)
        cl.check("add_item before path", "Insert before 2 gives item_path='2'",
                 d.get("item_path") == "2", f"got: {r!r}")
        r = execute_tool("todo_list", {"action": "get_item", "item_path": "2"}, env.session_data)
        cl.check("add_item before text", "Item at position 2 is the newly inserted item",
                 r == "inserted before 2", f"got: {r!r}")

        # list is now: 1=step ONE, 2=inserted before 2, 3=step two
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "after": 1, "text": "inserted after 1"}, env.session_data)
        d = _j(r)
        cl.check("add_item after path", "Insert after 1 gives item_path='2'",
                 d.get("item_path") == "2", f"got: {r!r}")
        r = execute_tool("todo_list", {"action": "get_item", "item_path": "2"}, env.session_data)
        cl.check("add_item after text", "Item at position 2 is the after-inserted item",
                 r == "inserted after 1", f"got: {r!r}")

        # ----------------------------------------------------------------
        # add_many_items
        # ----------------------------------------------------------------

        ms: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "A"}, ms)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "B"}, ms)

        r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": "", "texts": ["X", "Y", "Z"]}, ms)
        d = _j(r)
        added = d.get("items", [])
        cl.check("add_many_items count", "add_many_items returns 3 items",
                 len(added) == 3, f"got: {r!r}")
        cl.check("add_many_items paths", "add_many_items items have correct paths",
                 [it["item_path"] for it in added] == ["3", "4", "5"], f"got: {added!r}")

        r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": "", "before": 1, "texts": ["first", "second"]}, ms)
        d = _j(r)
        added = d.get("items", [])
        cl.check("add_many_items before paths", "add_many_items before=1 gives paths 1 and 2",
                 [it["item_path"] for it in added] == ["1", "2"], f"got: {added!r}")
        r = execute_tool("todo_list", {"action": "get_item", "item_path": "1"}, ms)
        cl.check("add_many_items before text", "First item is now 'first'",
                 r == "first", f"got: {r!r}")

        # ----------------------------------------------------------------
        # Promotion: add child to leaf
        # ----------------------------------------------------------------

        ps: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent task"}, ps)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "sibling"}, ps)

        # Promote item 1 by adding a child
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child A"}, ps)
        d = _j(r)
        cl.check("promotion child path", "First child of promoted item has path '1.1'",
                 d.get("item_path") == "1.1", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child B"}, ps)
        cl.check("promotion second child path", "Second child has path '1.2'",
                 _j(r).get("item_path") == "1.2", f"got: {r!r}")

        # Item 1 text unchanged after promotion
        r = execute_tool("todo_list", {"action": "get_item", "item_path": "1"}, ps)
        cl.check("promotion text preserved", "Promoted item keeps its original text",
                 r == "parent task", f"got: {r!r}")

        # update_item on promoted item (renames the group)
        r = execute_tool("todo_list", {"action": "update_item", "item_path": "1", "text": "renamed group"}, ps)
        cl.check("update promoted item", "update_item works on promoted item",
                 _j(r).get("text") == "renamed group", f"got: {r!r}")

        # ----------------------------------------------------------------
        # list / list_formatted with item_path (subtree)
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "list", "item_path": "1"}, ps)
        sub_items = _j(r).get("items", [])
        cl.check("list subtree count", "list(item_path='1') returns 2 children",
                 len(sub_items) == 2, f"got: {r!r}")
        cl.check("list subtree paths", "Children have paths 1.1 and 1.2",
                 [it["item_path"] for it in sub_items] == ["1.1", "1.2"],
                 f"got: {sub_items!r}")

        r = execute_tool("todo_list", {"action": "list_formatted", "item_path": "1"}, ps)
        cl.check("list_formatted subtree has children", "Subtree formatted output shows children",
                 "child A" in r and "child B" in r, f"got: {r!r}")
        cl.check("list_formatted subtree excludes sibling", "Subtree does not include sibling",
                 "sibling" not in r, f"got: {r!r}")
        cl.check("list_formatted subtree paths", "Subtree shows 1.1. and 1.2. path notation",
                 "1.1." in r and "1.2." in r, f"got: {r!r}")

        # ----------------------------------------------------------------
        # close_item / reopen_item — promoted item errors
        # ----------------------------------------------------------------

        r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, ps)
        d = _j(r)
        cl.check("close_item promoted error", "close_item on promoted item returns error",
                 "error" in d, f"got: {r!r}")
        cl.check("close_item promoted directive", "Error message is informative about auto-close",
                 "children" in d.get("error", "").lower() or "sub-list" in d.get("error", "").lower(),
                 f"got: {d.get('error')!r}")

        r = execute_tool("todo_list", {"action": "reopen_item", "item_path": "1"}, ps)
        d = _j(r)
        cl.check("reopen_item promoted error", "reopen_item on promoted item returns error",
                 "error" in d, f"got: {r!r}")

        # ----------------------------------------------------------------
        # Derived closed state for promoted items
        # ----------------------------------------------------------------

        dc: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dc)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child 1"}, dc)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child 2"}, dc)

        # Close one child — parent stays open
        execute_tool("todo_list", {"action": "close_item", "item_path": "1.1"}, dc)
        r = execute_tool("todo_list", {"action": "list"}, dc)
        root_item = _j(r).get("items", [{}])[0]
        cl.check("promoted partial close stays open", "Promoted item is open when only one child closed",
                 root_item.get("status") == "open", f"got: {root_item!r}")

        # Close second child — parent becomes closed
        execute_tool("todo_list", {"action": "close_item", "item_path": "1.2"}, dc)
        r = execute_tool("todo_list", {"action": "list"}, dc)
        root_item = _j(r).get("items", [{}])[0]
        cl.check("promoted all children closed", "Promoted item is closed when all children closed",
                 root_item.get("status") == "closed", f"got: {root_item!r}")

        # ----------------------------------------------------------------
        # all-done notification
        # ----------------------------------------------------------------

        ad: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "only task"}, ad)
        r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, ad)
        msg = _j(r).get("message", "")
        cl.check("all done message", "Closing last item triggers all-done notice",
                 "all todo list items are now complete" in msg, f"got: {r!r}")

        # all-done requires ALL closed (including promoted items via children)
        ad2: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, ad2)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child"}, ad2)
        r = execute_tool("todo_list", {"action": "close_item", "item_path": "1.1"}, ad2)
        msg = _j(r).get("message", "")
        cl.check("all done via promoted item", "Closing last leaf triggers all-done when parent auto-closes",
                 "all todo list items are now complete" in msg, f"got: {r!r}")

        # all-done does NOT fire when other items remain open
        ad3: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "task 1"}, ad3)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "task 2"}, ad3)
        r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, ad3)
        msg = _j(r).get("message", "")
        cl.check("no all-done with open items", "all-done does not fire when other items remain open",
                 "all todo list items are now complete" not in msg, f"got: {r!r}")

        # ----------------------------------------------------------------
        # delete_item — with children
        # ----------------------------------------------------------------

        dh: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dh)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child"}, dh)

        r = execute_tool("todo_list", {"action": "delete_item", "item_path": "1"}, dh)
        d = _j(r)
        cl.check("delete_item with children no cascade", "delete_item on item with children errors without cascade",
                 "error" in d, f"got: {r!r}")
        cl.check("delete_item directive", "Error message mentions cascade_delete=true",
                 "cascade_delete" in d.get("error", ""), f"got: {d.get('error')!r}")

        r = execute_tool("todo_list", {"action": "delete_item", "item_path": "1", "cascade_delete": True}, dh)
        cl.check("delete_item cascade success", "cascade_delete=true removes item and children",
                 "error" not in _j(r), f"got: {r!r}")
        r = execute_tool("todo_list", {"action": "list"}, dh)
        cl.check("delete_item cascade list empty", "List is empty after cascade delete",
                 _j(r).get("items") == [], f"got: {r!r}")

        # ----------------------------------------------------------------
        # Deeply nested: grandchild
        # ----------------------------------------------------------------

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

        # ----------------------------------------------------------------
        # auto_strip_leading_numbers — including dot-delimited patterns
        # ----------------------------------------------------------------

        as_: dict = {}
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "1. numbered item"}, as_)
        cl.check("auto_strip simple", "Leading '1. ' stripped",
                 _j(r).get("text") == "numbered item", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "1.2. dot-delimited"}, as_)
        cl.check("auto_strip dot-delimited", "Leading '1.2. ' stripped",
                 _j(r).get("text") == "dot-delimited", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "3) paren style"}, as_)
        cl.check("auto_strip paren", "Leading '3) ' stripped",
                 _j(r).get("text") == "paren style", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "2) keep prefix", "auto_strip_leading_numbers": False}, as_)
        cl.check("auto_strip disabled", "Prefix preserved when auto_strip=False",
                 _j(r).get("text") == "2) keep prefix", f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": "", "texts": ["1. first", "1.2. second"]}, as_)
        stripped = [it["text"] for it in _j(r).get("items", [])]
        cl.check("auto_strip in add_many_items", "Leading numbers stripped from all texts in add_many_items",
                 stripped == ["first", "second"], f"got: {stripped!r}")

        # ----------------------------------------------------------------
        # Error cases — all must be informative
        # ----------------------------------------------------------------

        err_s: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "item 1"}, err_s)

        # item_path doesn't exist
        r = execute_tool("todo_list", {"action": "get_item", "item_path": "99"}, err_s)
        d = _j(r)
        cl.check("error item not found", "get_item with bad path returns error",
                 "error" in d, f"got: {r!r}")
        cl.check("error item not found directive", "Error message is informative",
                 "does not exist" in d.get("error", "") or "list" in d.get("error", "").lower(),
                 f"got: {d.get('error')!r}")

        # parent_path doesn't exist
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "5", "text": "x"}, err_s)
        d = _j(r)
        cl.check("error parent not found", "add_item with bad parent_path returns error",
                 "error" in d, f"got: {r!r}")

        # before out of range
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "before": 99, "text": "x"}, err_s)
        d = _j(r)
        cl.check("error before out of range", "before out of range returns error",
                 "error" in d, f"got: {r!r}")
        cl.check("error before directive", "before error mentions range",
                 "out of range" in d.get("error", "") or "range" in d.get("error", ""),
                 f"got: {d.get('error')!r}")

        # after out of range
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "after": 99, "text": "x"}, err_s)
        d = _j(r)
        cl.check("error after out of range", "after out of range returns error",
                 "error" in d, f"got: {r!r}")

        # before and after both given
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "before": 1, "after": 1, "text": "x"}, err_s)
        d = _j(r)
        cl.check("error before and after", "Both before and after returns error",
                 "error" in d, f"got: {r!r}")
        cl.check("error before and after directive", "Error mentions mutually exclusive",
                 "mutually exclusive" in d.get("error", ""),
                 f"got: {d.get('error')!r}")

        # before on empty list
        empty_s: dict = {}
        r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "before": 1, "text": "x"}, empty_s)
        d = _j(r)
        cl.check("error before empty list", "before on empty list returns error",
                 "error" in d, f"got: {r!r}")

        # Missing required args
        r = execute_tool("todo_list", {"action": "add_item"}, err_s)
        cl.check("error add_item missing text", "add_item without text returns error",
                 "error" in _j(r), f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": ""}, err_s)
        cl.check("error add_many_items missing texts", "add_many_items without texts returns error",
                 "error" in _j(r), f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "get_item"}, err_s)
        cl.check("error get_item missing path", "get_item without item_path returns error",
                 "error" in _j(r), f"got: {r!r}")

        r = execute_tool("todo_list", {"action": "update_item", "item_path": "1"}, err_s)
        cl.check("error update_item missing text", "update_item without text returns error",
                 "error" in _j(r), f"got: {r!r}")

        # Navigate through leaf (no sub_list)
        nav_s: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "leaf"}, nav_s)
        r = execute_tool("todo_list", {"action": "get_item", "item_path": "1.1"}, nav_s)
        d = _j(r)
        cl.check("error navigate through leaf", "Navigating through a leaf returns error",
                 "error" in d, f"got: {r!r}")
        cl.check("error navigate directive", "Error mentions no children",
                 "no children" in d.get("error", "").lower(),
                 f"got: {d.get('error')!r}")

        # ----------------------------------------------------------------
        # Demotion: deleting the last child of a promoted item
        # ----------------------------------------------------------------

        dm: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "only child"}, dm)

        # Item 1 is now promoted; delete its only child
        execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm)

        # Item 1 should now be a plain leaf (no children)
        r = execute_tool("todo_list", {"action": "list"}, dm)
        items = _j(r).get("items", [])
        cl.check("demotion leaf after last child deleted", "Item is demoted to leaf after last child deleted",
                 len(items) == 1 and "children" not in items[0], f"got: {items!r}")

        # Should be closeable again as a leaf
        r = execute_tool("todo_list", {"action": "close_item", "item_path": "1"}, dm)
        cl.check("demotion leaf closeable", "Demoted item can be closed as a leaf",
                 "error" not in _j(r), f"got: {r!r}")

        # Captured status: delete a closed-last-child → item demotes as closed
        dm2: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm2)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "only child"}, dm2)
        execute_tool("todo_list", {"action": "close_item", "item_path": "1.1"}, dm2)
        execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm2)
        r = execute_tool("todo_list", {"action": "list"}, dm2)
        items = _j(r).get("items", [])
        cl.check("demotion captures closed status", "Demoted item captures 'closed' when last child was closed",
                 items[0].get("status") == "closed", f"got: {items!r}")

        # Captured status: delete an open-last-child → item demotes as open
        dm3: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm3)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "only child"}, dm3)
        # child remains open; delete it
        execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm3)
        r = execute_tool("todo_list", {"action": "list"}, dm3)
        items = _j(r).get("items", [])
        cl.check("demotion captures open status", "Demoted item captures 'open' when last child was open",
                 items[0].get("status") == "open", f"got: {items!r}")

        # Deleting a non-last child does NOT demote
        dm4: dict = {}
        execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "parent"}, dm4)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child A"}, dm4)
        execute_tool("todo_list", {"action": "add_item", "parent_path": "1", "text": "child B"}, dm4)
        execute_tool("todo_list", {"action": "delete_item", "item_path": "1.1"}, dm4)
        r = execute_tool("todo_list", {"action": "list"}, dm4)
        items = _j(r).get("items", [])
        cl.check("no demotion with remaining child", "Item not demoted when children remain after delete",
                 items[0].get("children") is not None, f"got: {items!r}")

        # Unknown action (schema validation rejects removed actions before execution)
        r = execute_tool("todo_list", {"action": "get_all"}, err_s)
        cl.check("unknown action", "Old action 'get_all' is rejected",
                 "error" in _j(r) or "fail" in r.lower() or "error" in r.lower(), f"got: {r!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
