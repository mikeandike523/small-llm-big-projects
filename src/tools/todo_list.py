from __future__ import annotations

import json
import re

LEAVE_OUT = "KEEP"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "todo_list",
        "description": (
            "Manage the session todo list. "
            "Items are addressed by dot-delimited 1-indexed paths: '1', '1.1', '2.3.1', etc. "
            "Adding a child to a plain item promotes it to a sub-list parent — "
            "its text becomes the group name. "
            "Sub-list parents close automatically when all their descendants are closed; "
            "they cannot be closed or reopened directly. "
            "Use this tool to plan and track concrete steps toward the user's current goal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "list_formatted",
                        "get_item",
                        "add_item",
                        "add_many_items",
                        "update_item",
                        "delete_item",
                        "close_item",
                        "reopen_item",
                    ],
                    "description": (
                        "The operation to perform.\n"
                        "list: return items as JSON. "
                        "Pass item_path to list only that item's children (no header). "
                        "Omit for the full tree.\n"
                        "list_formatted: same as list but human-readable plain text.\n"
                        "get_item: return the raw text of the item at item_path (no subtree). "
                        "Call list(item_path=...) to inspect children.\n"
                        "add_item: add one item. Requires parent_path (empty or omit for root) and text. "
                        "If parent_path points to a plain leaf item it is promoted to a sub-list parent. "
                        "Use before or after (1-indexed integers) to control insertion position; "
                        "omit both to append.\n"
                        "add_many_items: same as add_item but takes texts (array of strings). "
                        "Items are inserted consecutively in order.\n"
                        "update_item: set the text of item at item_path. "
                        "Works on leaf items and sub-list parents (renames the group).\n"
                        "delete_item: remove item at item_path. "
                        "Errors if item has children unless cascade_delete=true.\n"
                        "close_item: mark a leaf item as done. "
                        "Sub-list parents close automatically when all descendants are closed "
                        "and cannot be closed directly.\n"
                        "reopen_item: mark a leaf item as open again. "
                        "Sub-list parents have no direct open/closed state — reopen a child instead."
                    ),
                },
                "item_path": {
                    "type": "string",
                    "description": (
                        "Dot-delimited 1-indexed path to a specific item ('1', '1.2', '2.3.1'). "
                        "Required for: get_item, update_item, delete_item, close_item, reopen_item. "
                        "Optional for: list, list_formatted (shows that item's children when given)."
                    ),
                },
                "parent_path": {
                    "type": "string",
                    "description": (
                        "Dot-delimited path to the parent item whose child list to add to. "
                        "Empty string or omit for root. "
                        "Required for: add_item, add_many_items."
                    ),
                },
                "before": {
                    "type": "integer",
                    "description": (
                        "1-indexed position within the resolved list to insert before. "
                        "Mutually exclusive with after. Optional for add_item, add_many_items."
                    ),
                },
                "after": {
                    "type": "integer",
                    "description": (
                        "1-indexed position within the resolved list to insert after. "
                        "Mutually exclusive with before. Optional for add_item, add_many_items."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "Item text. Required for add_item, update_item.",
                },
                "texts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of item texts. Required for add_many_items.",
                },
                "cascade_delete": {
                    "type": "boolean",
                    "description": (
                        "For delete_item only. Default false. "
                        "If false, errors when the item has children. "
                        "If true, deletes the item and all descendants."
                    ),
                },
                "auto_strip_leading_numbers": {
                    "type": "boolean",
                    "description": (
                        "Default true. Strips leading numeric list prefixes from text or texts before "
                        "storing. Handles: bare multi-part numbers followed by whitespace ('2.2 ', "
                        "'1.2.3 '), numbers with a trailing dot ('1. ', '2.2. '), numbers with a "
                        "trailing paren ('3) ', '1.1) '), and numbers with both ('1.1.) ', '2.2.) '). "
                        "Single bare digits ('1 ') are NOT stripped."
                    ),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def format_items_for_ui(items: list, path_prefix: list[int] | None = None) -> list:
    """Return items in the UI wire format (item_path, text, derived status, children).

    Used by socket_handlers to build todo_list_update payloads and todo_snapshot.
    """
    return [_fmt_item(items, i, path_prefix) for i in range(len(items))]


# Matches leading numbering prefixes at the start of a string, followed by whitespace:
#   multi-part with no trailing marker: "2.2 ", "1.2.3 "
#   with trailing dot (optionally + paren): "1. ", "2.2. ", "1.1.) "
#   with trailing paren only: "3) ", "1.1) "
_LEADING_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)+\s+|^\d+(?:\.\d+)*(?:\.\)?|\))\s+")


def _strip_leading_number(s: str) -> str:
    return _LEADING_NUMBER_RE.sub("", s, count=1)


def _get_root(session_data: dict) -> list:
    """Return the root todo list from session_data, creating it if absent."""
    todo = session_data.get("todo_list")
    if not isinstance(todo, list):
        todo = []
        session_data["todo_list"] = todo
    return todo


def _parse_path(path_str: str) -> tuple[list[int] | None, str | None]:
    """Parse a dot-delimited path string into a list of 1-based ints.

    Returns (segments, None) on success, (None, error_str) on failure.
    Empty string returns ([], None).
    """
    if not path_str:
        return [], None
    segments = []
    for part in path_str.split("."):
        try:
            n = int(part)
            if n < 1:
                return None, f"Path segment '{part}' must be a positive integer."
            segments.append(n)
        except ValueError:
            return None, f"Path segment '{part}' is not a valid integer."
    return segments, None


def _context_hint(parent_segs: list[int]) -> str:
    """Build a helpful list() call hint pointing at the given parent path."""
    if not parent_segs:
        return "Use list() to inspect the root list."
    parent = ".".join(str(s) for s in parent_segs)
    return f"Use list(item_path='{parent}') to inspect."


def _resolve_item(
    root_items: list, segments: list[int]
) -> tuple[list | None, int | None, str | None]:
    """Navigate to the item at `segments`, returning (parent_list, 1-based-idx, None).

    All segments must refer to existing items.
    Intermediate items must have non-empty sub_lists to navigate through.
    Returns (None, None, error_str) on failure with a directive error message.
    """
    if not segments:
        return None, None, "item_path is required."

    current = root_items
    for i, seg in enumerate(segments[:-1]):
        count = len(current)
        noun = "item" if count == 1 else "items"
        if seg < 1 or seg > count:
            path_str = ".".join(str(s) for s in segments[: i + 1])
            hint = _context_hint(segments[:i])
            return None, None, (
                f"Item '{path_str}' does not exist — "
                f"the containing list has {count} {noun}. {hint}"
            )
        item = current[seg - 1]
        sub = item.get("sub_list")
        if not sub:
            path_str = ".".join(str(s) for s in segments[: i + 1])
            hint = _context_hint(segments[:i])
            return None, None, (
                f"Item '{path_str}' has no children to navigate through. {hint}"
            )
        current = sub

    last = segments[-1]
    count = len(current)
    noun = "item" if count == 1 else "items"
    if last < 1 or last > count:
        path_str = ".".join(str(s) for s in segments)
        hint = _context_hint(segments[:-1])
        return None, None, (
            f"Item '{path_str}' does not exist — "
            f"the containing list has {count} {noun}. {hint}"
        )

    return current, last, None


def _resolve_add_target(
    root_items: list, parent_segs: list[int]
) -> tuple[list | None, str | None]:
    """Get the child list to add items to.

    If parent_segs is empty, returns root_items.
    Otherwise navigates to the item at parent_segs and returns its sub_list,
    creating it if absent (promotion of leaf to sub-list parent).
    All intermediate items must exist and have sub_lists to navigate through.
    Returns (target_list, None) on success, (None, error_str) on failure.
    """
    if not parent_segs:
        return root_items, None

    current = root_items
    for i, seg in enumerate(parent_segs):
        count = len(current)
        noun = "item" if count == 1 else "items"
        if seg < 1 or seg > count:
            path_str = ".".join(str(s) for s in parent_segs[: i + 1])
            hint = _context_hint(parent_segs[:i])
            return None, (
                f"Item '{path_str}' does not exist — "
                f"the containing list has {count} {noun}. {hint}"
            )
        item = current[seg - 1]
        is_last = i == len(parent_segs) - 1
        if is_last:
            # This is the target parent — promote if it has no sub_list yet
            if "sub_list" not in item:
                item["sub_list"] = []
            return item["sub_list"], None
        sub = item.get("sub_list")
        if not sub:
            path_str = ".".join(str(s) for s in parent_segs[: i + 1])
            hint = _context_hint(parent_segs[:i])
            return None, (
                f"Item '{path_str}' has no children to navigate through. {hint}"
            )
        current = sub

    return root_items, None  # unreachable; satisfies type checker


def _is_promoted(item: dict) -> bool:
    """True if the item has been promoted to a sub-list parent (has a sub_list key)."""
    return "sub_list" in item


def _all_closed(items: list) -> bool:
    """Return True if the list is non-empty and all items are recursively closed."""
    if not items:
        return False
    for item in items:
        if _effective_status(item) != "closed":
            return False
    return True


def _effective_status(item: dict) -> str:
    """Compute effective status.

    Promoted items: 'closed' iff all descendants are closed (recursive).
    Leaf items: stored status field.
    """
    if _is_promoted(item):
        return "closed" if _all_closed(item["sub_list"]) else "open"
    return item.get("status", "open")


def _compute_path(parent_segs: list[int], child_pos: int) -> str:
    """Build a dot-delimited path string for a child at 1-based child_pos."""
    return ".".join(str(s) for s in (parent_segs + [child_pos]))


def _fmt_item(
    items: list, idx: int, path_prefix: list[int] | None = None
) -> dict:
    """Return a serialisable item dict with full item_path, recursively including children."""
    item = items[idx]
    current_path = (path_prefix or []) + [idx + 1]
    path_str = ".".join(str(n) for n in current_path)
    result: dict = {
        "item_path": path_str,
        "text": item["text"],
        "status": _effective_status(item),
    }
    sub = item.get("sub_list")
    if sub:
        result["children"] = [_fmt_item(sub, j, current_path) for j in range(len(sub))]
    return result


def _format_tree(
    items: list, indent: str = "", path_prefix: list[int] | None = None
) -> list[str]:
    """Recursively format the todo tree as human-readable lines."""
    lines = []
    for i, item in enumerate(items):
        current_path = (path_prefix or []) + [i + 1]
        path_str = ".".join(str(n) for n in current_path)
        checkbox = "[x]" if _effective_status(item) == "closed" else "[ ]"
        lines.append(f"{indent}{checkbox} {path_str}. {item['text']}")
        sub = item.get("sub_list")
        if sub:
            lines.extend(_format_tree(sub, indent + "    ", current_path))
    return lines


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    action = args.get("action", "")
    item_path_str = args.get("item_path") or ""
    parent_path_str = args.get("parent_path") or ""
    before = args.get("before")
    after = args.get("after")
    text = args.get("text")
    texts = args.get("texts")
    cascade_delete = args.get("cascade_delete", False)
    auto_strip = args.get("auto_strip_leading_numbers", True)

    if auto_strip:
        if text is not None:
            text = _strip_leading_number(text)
        if texts is not None:
            texts = [_strip_leading_number(t) for t in texts]

    root_items = _get_root(session_data)

    # ---- list ----
    if action == "list":
        if item_path_str:
            segs, err = _parse_path(item_path_str)
            if err:
                return json.dumps({"error": err})
            parent_list, last, err = _resolve_item(root_items, segs)
            if err:
                return json.dumps({"error": err})
            item = parent_list[last - 1]
            sub = item.get("sub_list")
            if not sub:
                return json.dumps({
                    "error": (
                        f"Item '{item_path_str}' has no children. "
                        "Use list() to see the full tree."
                    )
                })
            return json.dumps({
                "items": [_fmt_item(sub, j, segs) for j in range(len(sub))]
            })
        return json.dumps({
            "items": [_fmt_item(root_items, i) for i in range(len(root_items))]
        })

    # ---- list_formatted ----
    if action == "list_formatted":
        if item_path_str:
            segs, err = _parse_path(item_path_str)
            if err:
                return json.dumps({"error": err})
            parent_list, last, err = _resolve_item(root_items, segs)
            if err:
                return json.dumps({"error": err})
            item = parent_list[last - 1]
            sub = item.get("sub_list")
            if not sub:
                return json.dumps({
                    "error": (
                        f"Item '{item_path_str}' has no children. "
                        "Use list() to see the full tree."
                    )
                })
            return "\n".join(_format_tree(sub, "", segs))
        if not root_items:
            return "(empty todo list)"
        return "\n".join(_format_tree(root_items))

    # ---- get_item ----
    if action == "get_item":
        if not item_path_str:
            return json.dumps({"error": "get_item requires item_path."})
        segs, err = _parse_path(item_path_str)
        if err:
            return json.dumps({"error": err})
        parent_list, last, err = _resolve_item(root_items, segs)
        if err:
            return json.dumps({"error": err})
        return parent_list[last - 1]["text"]

    # ---- add_item / add_many_items ----
    if action in ("add_item", "add_many_items"):
        if action == "add_item" and not text:
            return json.dumps({"error": "add_item requires text."})
        if action == "add_many_items" and not texts:
            return json.dumps({
                "error": "add_many_items requires texts (a non-empty array of strings)."
            })
        if before is not None and after is not None:
            return json.dumps({
                "error": "before and after are mutually exclusive — provide one or neither."
            })

        parent_segs, err = _parse_path(parent_path_str)
        if err:
            return json.dumps({"error": err})
        target_list, err = _resolve_add_target(root_items, parent_segs)
        if err:
            return json.dumps({"error": err})

        n = len(target_list)
        where = f"'{parent_path_str}'" if parent_path_str else "the root list"

        if before is not None:
            if n == 0:
                return json.dumps({
                    "error": (
                        f"before={before} cannot be used — {where} is empty. "
                        "Omit before/after to append the first item."
                    )
                })
            if before < 1 or before > n:
                noun = "item" if n == 1 else "items"
                return json.dumps({
                    "error": f"before={before} is out of range — {where} has {n} {noun}."
                })
            insert_idx = before - 1
        elif after is not None:
            if n == 0:
                return json.dumps({
                    "error": (
                        f"after={after} cannot be used — {where} is empty. "
                        "Omit before/after to append the first item."
                    )
                })
            if after < 1 or after > n:
                noun = "item" if n == 1 else "items"
                return json.dumps({
                    "error": f"after={after} is out of range — {where} has {n} {noun}."
                })
            insert_idx = after  # insert after position `after` = at 0-based index `after`
        else:
            insert_idx = n  # append

        if action == "add_item":
            target_list.insert(insert_idx, {"text": text, "status": "open"})
            path_str = _compute_path(parent_segs, insert_idx + 1)
            return json.dumps({
                "item_path": path_str,
                "text": text,
                "message": f"Added item '{path_str}': \"{text}\"",
            })
        else:  # add_many_items
            new_items = [{"text": t, "status": "open"} for t in texts]
            target_list[insert_idx:insert_idx] = new_items
            paths = [
                _compute_path(parent_segs, insert_idx + 1 + i)
                for i in range(len(texts))
            ]
            return json.dumps({
                "items": [{"item_path": p, "text": t} for p, t in zip(paths, texts)],
                "message": f"Added {len(texts)} item(s): {', '.join(paths)}",
            })

    # ---- update_item ----
    if action == "update_item":
        if not item_path_str:
            return json.dumps({"error": "update_item requires item_path."})
        if not text:
            return json.dumps({"error": "update_item requires text."})
        segs, err = _parse_path(item_path_str)
        if err:
            return json.dumps({"error": err})
        parent_list, last, err = _resolve_item(root_items, segs)
        if err:
            return json.dumps({"error": err})
        parent_list[last - 1]["text"] = text
        return json.dumps({
            "item_path": item_path_str,
            "text": text,
            "message": f"Updated item '{item_path_str}': \"{text}\"",
        })

    # ---- delete_item ----
    if action == "delete_item":
        if not item_path_str:
            return json.dumps({"error": "delete_item requires item_path."})
        segs, err = _parse_path(item_path_str)
        if err:
            return json.dumps({"error": err})
        parent_list, last, err = _resolve_item(root_items, segs)
        if err:
            return json.dumps({"error": err})
        item = parent_list[last - 1]
        if _is_promoted(item) and not cascade_delete:
            return json.dumps({
                "error": (
                    f"Item '{item_path_str}' has children and cannot be deleted without cascade. "
                    "Delete its children individually first, or retry with cascade_delete=true."
                )
            })

        # Demotion: if this deletion empties a promoted parent, capture its derived
        # status now (before the child disappears) then demote it back to a leaf.
        owner_item = None
        captured_status = None
        if len(segs) >= 2 and len(parent_list) == 1:
            owner_parent, owner_last, owner_err = _resolve_item(root_items, segs[:-1])
            if not owner_err:
                owner_item = owner_parent[owner_last - 1]
                captured_status = _effective_status(owner_item)

        removed = parent_list.pop(last - 1)

        if owner_item is not None:
            owner_item.pop("sub_list", None)
            owner_item["status"] = captured_status

        return json.dumps({
            "item_path": item_path_str,
            "text": removed["text"],
            "message": f"Deleted item '{item_path_str}': \"{removed['text']}\"",
        })

    # ---- close_item ----
    if action == "close_item":
        if not item_path_str:
            return json.dumps({"error": "close_item requires item_path."})
        segs, err = _parse_path(item_path_str)
        if err:
            return json.dumps({"error": err})
        parent_list, last, err = _resolve_item(root_items, segs)
        if err:
            return json.dumps({"error": err})
        item = parent_list[last - 1]
        if _is_promoted(item):
            return json.dumps({
                "error": (
                    f"Item '{item_path_str}' is a sub-list parent and cannot be closed directly. "
                    "It closes automatically when all its children are closed. "
                    f"Use list(item_path='{item_path_str}') to inspect its children."
                )
            })
        item["status"] = "closed"
        msg = f"Closed item '{item_path_str}': \"{item['text']}\""
        if root_items and _all_closed(root_items):
            msg += " -- all todo list items are now complete"
        return json.dumps({
            "item_path": item_path_str,
            "status": "closed",
            "message": msg,
        })

    # ---- reopen_item ----
    if action == "reopen_item":
        if not item_path_str:
            return json.dumps({"error": "reopen_item requires item_path."})
        segs, err = _parse_path(item_path_str)
        if err:
            return json.dumps({"error": err})
        parent_list, last, err = _resolve_item(root_items, segs)
        if err:
            return json.dumps({"error": err})
        item = parent_list[last - 1]
        if _is_promoted(item):
            return json.dumps({
                "error": (
                    f"Item '{item_path_str}' is a sub-list parent and has no direct open/closed state. "
                    "To reopen it, reopen one of its children. "
                    f"Use list(item_path='{item_path_str}') to inspect its children."
                )
            })
        item["status"] = "open"
        return json.dumps({
            "item_path": item_path_str,
            "status": "open",
            "message": f"Reopened item '{item_path_str}': \"{item['text']}\"",
        })

    return json.dumps({"error": f"Unknown action '{action}'."})
