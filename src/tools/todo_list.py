from __future__ import annotations

import json

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "todo_list",
        "description": (
            "Manage the session todo list. "
            "The list is ordered and 1-indexed. "
            "Use this to track concrete steps toward the user's current goal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "get_all",
                        "get_item",
                        "add_item",
                        "insert_before",
                        "insert_after",
                        "delete_item",
                        "modify_item",
                        "close_item",
                        "reopen_item",
                    ],
                    "description": (
                        "The operation to perform. "
                        "get_all: return all items. "
                        "get_item: return one item by item_number. "
                        "add_item: append a new item (requires text). "
                        "insert_before: insert before item_number (requires item_number and text). "
                        "insert_after: insert after item_number (requires item_number and text). "
                        "delete_item: remove item at item_number (requires item_number). "
                        "modify_item: change text of item at item_number (requires item_number and text). "
                        "close_item: mark item as closed/done (requires item_number). "
                        "reopen_item: mark item as open again (requires item_number)."
                    ),
                },
                "item_number": {
                    "type": "integer",
                    "description": (
                        "1-indexed position of the target item. "
                        "Required for: get_item, insert_before, insert_after, "
                        "delete_item, modify_item, close_item, reopen_item."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Text content for the item. "
                        "Required for: add_item, insert_before, insert_after, modify_item."
                    ),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}

# Actions that require item_number
_NEEDS_ITEM_NUMBER = {
    "get_item", "insert_before", "insert_after",
    "delete_item", "modify_item", "close_item", "reopen_item",
}

# Actions that require text
_NEEDS_TEXT = {"add_item", "insert_before", "insert_after", "modify_item"}


def _get_list(session_data: dict) -> list:
    """Return the todo list from session_data, auto-creating it if absent."""
    todo = session_data.get("todo_list")
    if not isinstance(todo, list):
        todo = []
        session_data["todo_list"] = todo
    return todo


def _check_item_number(items: list, n: int) -> str | None:
    """Return an error string if n is out of range, else None."""
    count = len(items)
    if n < 1 or n > count:
        noun = "item" if count == 1 else "items"
        return f"item_number {n} is out of range (list has {count} {noun})"
    return None


def _fmt_item(items: list, idx: int) -> dict:
    """Return a serialisable item dict with its 1-indexed item_number."""
    return {
        "item_number": idx + 1,
        "text": items[idx]["text"],
        "status": items[idx]["status"],
    }


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    action = args.get("action", "")
    item_number = args.get("item_number")
    text = args.get("text")

    # --- Validate required parameters ---
    if action in _NEEDS_ITEM_NUMBER and item_number is None:
        return json.dumps({"error": f"action '{action}' requires 'item_number'"})
    if action in _NEEDS_TEXT and not text:
        return json.dumps({"error": f"action '{action}' requires 'text'"})

    items = _get_list(session_data)

    # --- get_all ---
    if action == "get_all":
        return json.dumps({"items": [_fmt_item(items, i) for i in range(len(items))]})

    # --- get_item ---
    if action == "get_item":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        return json.dumps({"item": _fmt_item(items, item_number - 1)})

    # --- add_item ---
    if action == "add_item":
        items.append({"text": text, "status": "open"})
        new_number = len(items)
        return json.dumps({
            "item": _fmt_item(items, new_number - 1),
            "message": f"Added item {new_number}: \"{text}\"",
        })

    # --- insert_before ---
    if action == "insert_before":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        idx = item_number - 1
        items.insert(idx, {"text": text, "status": "open"})
        return json.dumps({
            "item": _fmt_item(items, idx),
            "message": f"Inserted item {item_number}: \"{text}\"",
        })

    # --- insert_after ---
    if action == "insert_after":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        idx = item_number  # inserting *after* item_number means index = item_number (0-based)
        items.insert(idx, {"text": text, "status": "open"})
        new_number = idx + 1
        return json.dumps({
            "item": _fmt_item(items, idx),
            "message": f"Inserted item {new_number}: \"{text}\"",
        })

    # --- delete_item ---
    if action == "delete_item":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        idx = item_number - 1
        removed = items.pop(idx)
        return json.dumps({
            "deleted": {"item_number": item_number, "text": removed["text"], "status": removed["status"]},
            "message": f"Deleted item {item_number}: \"{removed['text']}\"",
        })

    # --- modify_item ---
    if action == "modify_item":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        idx = item_number - 1
        items[idx]["text"] = text
        return json.dumps({
            "item": _fmt_item(items, idx),
            "message": f"Modified item {item_number}: \"{text}\"",
        })

    # --- close_item ---
    if action == "close_item":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        idx = item_number - 1
        items[idx]["status"] = "closed"
        return json.dumps({
            "item": _fmt_item(items, idx),
            "message": f"Closed item {item_number}: \"{items[idx]['text']}\"",
        })

    # --- reopen_item ---
    if action == "reopen_item":
        err = _check_item_number(items, item_number)
        if err:
            return json.dumps({"error": err})
        idx = item_number - 1
        items[idx]["status"] = "open"
        return json.dumps({
            "item": _fmt_item(items, idx),
            "message": f"Reopened item {item_number}: \"{items[idx]['text']}\"",
        })

    return json.dumps({"error": f"Unknown action: '{action}'"})
