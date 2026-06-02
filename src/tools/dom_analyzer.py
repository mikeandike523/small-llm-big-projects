from __future__ import annotations

import json
import re
from typing import Optional

from src.tools._memory import ensure_session_memory

NO_STUB = True

DEFAULT_TRUNCATION_CHARS = 300
DEFAULT_ITEM_LIMIT = 30

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "dom_analyzer",
        "description": (
            "Analyze HTML stored in session memory. "
            "First use scrape_web_page with target='session_memory' to capture the raw HTML. "
            f"Results are truncated to {DEFAULT_TRUNCATION_CHARS} chars by default; set truncate_chars=0 to disable. "
            f"find_nodes returns up to {DEFAULT_ITEM_LIMIT} results by default; set limit=0 for unlimited. "
            "get_attribute is never truncated. "
            "Typical workflow: preview to orient, find_nodes to locate, get_node/get_attribute to inspect."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_key": {
                    "type": "string",
                    "description": "Session memory key containing the raw HTML.",
                },
                "action": {
                    "type": "string",
                    "enum": ["preview", "get_node", "get_attribute", "find_nodes", "list_children"],
                    "description": (
                        "preview: Render the DOM tree with truncated values. Good starting point. "
                        "get_node: Return the outer HTML of the target node, truncated by default. Accepts path or selector. "
                        "get_attribute: Return one attribute value (not truncated by default). Accepts path or selector. "
                        "find_nodes: Find elements by CSS selector; returns their paths + truncated markup. "
                        "list_children: List immediate element children as paths + key attributes (no markup)."
                    ),
                },
                "path": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Path from document root to the target node. "
                        "Steps: tag name ('div' = first div child), "
                        "'tag[N]' (0-based index among same-tag siblings, e.g. 'div[1]' = second div), "
                        "'[N]' (Nth element child regardless of tag), "
                        "'#text' or '#text[N]' (text node — rarely needed, must be last step). "
                        "Omit or use [] for document root. "
                        "Use find_nodes to discover paths by CSS selector."
                    ),
                },
                "attribute": {
                    "type": "string",
                    "description": "Attribute name. Required for get_attribute.",
                },
                "selector": {
                    "type": "string",
                    "description": (
                        "CSS selector string. Required for find_nodes. "
                        "For get_node/get_attribute, use instead of path to target the first matching element."
                    ),
                },
                "truncate_chars": {
                    "type": "integer",
                    "description": f"Max characters per node in output (default {DEFAULT_TRUNCATION_CHARS}). Set to 0 to disable truncation.",
                    "minimum": 0,
                },
                "depth": {
                    "type": "integer",
                    "description": "Max tree depth for preview. Omit for unlimited.",
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max results for find_nodes (default {DEFAULT_ITEM_LIMIT}). Set to 0 for unlimited.",
                    "minimum": 0,
                },
                "output_key": {
                    "type": "string",
                    "description": "Write result to this session memory key. Supported by get_node and get_attribute.",
                },
            },
            "required": ["memory_key", "action"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_STEP_TAG_IDX = re.compile(r"^(\w[\w-]*)\[(\d+)\]$")
_STEP_IDX_ONLY = re.compile(r"^\[(\d+)\]$")
_STEP_TEXT = re.compile(r"^#text(?:\[(\d+)\])?$")


def _resolve_path(soup, path: list[str]):
    """Return (node, error_str|None)."""
    from bs4 import Tag, NavigableString, Comment

    node = soup
    for i, step in enumerate(path):
        mt = _STEP_TEXT.match(step)
        if mt:
            text_nodes = [
                c for c in node.children
                if isinstance(c, NavigableString)
                and not isinstance(c, Comment)
                and str(c).strip()
            ]
            idx = int(mt.group(1)) if mt.group(1) is not None else 0
            if idx >= len(text_nodes):
                return None, (
                    f"Step {i} '{step}': only {len(text_nodes)} non-empty text node(s) found."
                )
            if i < len(path) - 1:
                return None, f"Step {i} '{step}': text nodes have no children; path cannot continue past here."
            return text_nodes[idx], None

        m = _STEP_TAG_IDX.match(step)
        m2 = _STEP_IDX_ONLY.match(step)
        if m:
            tag_name, idx = m.group(1), int(m.group(2))
            matches = [c for c in node.children if isinstance(c, Tag) and c.name == tag_name]
            if idx >= len(matches):
                return None, (
                    f"Step {i} '{step}': only {len(matches)} '{tag_name}' child element(s) "
                    f"(requested index {idx})."
                )
            node = matches[idx]
        elif m2:
            idx = int(m2.group(1))
            children = [c for c in node.children if isinstance(c, Tag)]
            if idx >= len(children):
                return None, f"Step {i} '[{idx}]': only {len(children)} element children."
            node = children[idx]
        else:
            found = next(
                (c for c in node.children if isinstance(c, Tag) and c.name == step),
                None,
            )
            if found is None:
                return None, f"Step {i} '{step}': no child element with tag '{step}'."
            node = found

    return node, None


def _node_to_path(node, soup) -> list[str]:
    """Canonical path list from soup root to a Tag."""
    from bs4 import Tag

    parts: list[str] = []
    current = node
    while current is not soup and current is not None:
        parent = current.parent
        if parent is None:
            break
        if isinstance(current, Tag):
            same = [c for c in parent.children if isinstance(c, Tag) and c.name == current.name]
            idx = same.index(current)
            parts.append(f"{current.name}[{idx}]" if len(same) > 1 else current.name)
        current = parent
    parts.reverse()
    return parts


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def _tc(args: dict) -> int:
    """Effective truncation length. 0 = unlimited."""
    return args.get("truncate_chars", DEFAULT_TRUNCATION_CHARS)


def _trunc(s: str, n: int) -> str:
    if n <= 0 or len(s) <= n:
        return s
    return s[:n] + "..."


# ---------------------------------------------------------------------------
# Preview tree renderer
# ---------------------------------------------------------------------------

def _attrs_str(tag, tc: int) -> str:
    parts = []
    for k, v in tag.attrs.items():
        val = " ".join(v) if isinstance(v, list) else str(v)
        parts.append(f'{k}="{_trunc(val, tc)}"')
    return (" " + " ".join(parts)) if parts else ""


def _is_whitespace(node) -> bool:
    from bs4 import NavigableString
    return isinstance(node, NavigableString) and not str(node).strip()


def _render_tree(node, tc: int, max_depth: Optional[int], indent: int = 0) -> list[str]:
    from bs4 import Tag, NavigableString, Comment

    lines: list[str] = []
    pfx = "  " * indent

    if isinstance(node, Comment):
        text = _trunc(str(node).strip(), tc)
        if text:
            lines.append(f"{pfx}<!-- {text} -->")
        return lines

    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text:
            lines.append(f"{pfx}{_trunc(text, tc)}")
        return lines

    if not isinstance(node, Tag):
        return lines

    if node.name == "[document]":
        for child in node.children:
            lines.extend(_render_tree(child, tc, max_depth, indent))
        return lines

    attrs = _attrs_str(node, tc)
    real_children = [c for c in node.children if not _is_whitespace(c)]
    elem_children = [c for c in real_children if isinstance(c, Tag)]

    if not real_children:
        lines.append(f"{pfx}<{node.name}{attrs} />")
    elif not elem_children:
        text = node.get_text(strip=True)
        lines.append(f"{pfx}<{node.name}{attrs}>{_trunc(text, tc)}</{node.name}>")
    else:
        lines.append(f"{pfx}<{node.name}{attrs}>")
        if max_depth is None or indent < max_depth:
            for child in node.children:
                lines.extend(_render_tree(child, tc, max_depth, indent + 1))
        else:
            lines.append(f"{pfx}  ...")
        lines.append(f"{pfx}</{node.name}>")

    return lines


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _action_preview(soup, args: dict) -> str:
    path = args.get("path") or []
    node, err = _resolve_path(soup, path)
    if err:
        return f"Error: {err}"
    lines = _render_tree(node, _tc(args), args.get("depth"))
    return "\n".join(lines) if lines else "(empty)"


def _check_selector_path_conflict(args: dict):
    """Return error string if both selector and path are provided, else None."""
    if args.get("selector") and args.get("path"):
        return "Provide either 'selector' or 'path', not both."
    return None


def _resolve_path_arg(soup, args: dict):
    """Return (node, error_str|None) via path resolution (no selector logic)."""
    return _resolve_path(soup, args.get("path") or [])


def _action_get_node(soup, args: dict, session_data: dict) -> str:
    from bs4 import Tag, NavigableString

    output_key = args.get("output_key")
    conflict = _check_selector_path_conflict(args)
    if conflict:
        return f"Error: {conflict}"

    selector = args.get("selector")
    if selector:
        try:
            matches = soup.select(selector)
        except Exception as e:
            return f"Error: Invalid CSS selector '{selector}': {e}"
        if not matches:
            return f"Error: No element matched selector '{selector}'."
        tc = _tc(args)
        if len(matches) == 1:
            result = _trunc(str(matches[0]), tc)
        else:
            parts = [f"[{i}] {_trunc(str(n), tc)}" for i, n in enumerate(matches)]
            result = "\n\n".join(parts)
        if output_key:
            ensure_session_memory(session_data)[output_key] = result
            return f"Node content written to session memory key '{output_key}'."
        return result

    node, err = _resolve_path_arg(soup, args)
    if err:
        return f"Error: {err}"

    if isinstance(node, NavigableString):
        result = _trunc(str(node), _tc(args))
    elif isinstance(node, Tag) and node.name != "[document]":
        result = _trunc(str(node), _tc(args))
    else:
        lines = _render_tree(node, _tc(args), None)
        result = "\n".join(lines) if lines else "(empty document)"

    if output_key:
        ensure_session_memory(session_data)[output_key] = result
        return f"Node content written to session memory key '{output_key}'."
    return result


def _action_get_attribute(soup, args: dict, session_data: dict) -> str:
    from bs4 import Tag

    attribute = args.get("attribute")
    output_key = args.get("output_key")

    if not attribute:
        return "Error: 'attribute' is required for get_attribute."
    conflict = _check_selector_path_conflict(args)
    if conflict:
        return f"Error: {conflict}"

    selector = args.get("selector")
    if selector:
        try:
            matches = soup.select(selector)
        except Exception as e:
            return f"Error: Invalid CSS selector '{selector}': {e}"
        if not matches:
            return f"Error: No element matched selector '{selector}'."
        if len(matches) > 1:
            return (
                f"Error: Selector '{selector}' matched {len(matches)} elements. "
                "get_attribute requires a single target — use a more specific selector, "
                ":nth-child(), or the 'path' argument."
            )
        node = matches[0]
    else:
        node, err = _resolve_path_arg(soup, args)
        if err:
            return f"Error: {err}"
    if not isinstance(node, Tag) or node.name == "[document]":
        return "Error: path points to document root or a text node, not an element."

    val = node.get(attribute)
    if val is None:
        return f"Attribute '{attribute}' not found on <{node.name}>."
    val = " ".join(val) if isinstance(val, list) else str(val)

    if output_key:
        ensure_session_memory(session_data)[output_key] = val
        return f"Attribute '{attribute}' written to session memory key '{output_key}'."
    return val


def _action_find_nodes(soup, args: dict) -> str:
    selector = args.get("selector")
    raw_limit = args.get("limit", DEFAULT_ITEM_LIMIT)
    tc = _tc(args)

    if not selector:
        return "Error: 'selector' is required for find_nodes."
    try:
        matches = soup.select(selector)
    except Exception as e:
        return f"Error: Invalid CSS selector '{selector}': {e}"
    if not matches:
        return f"No elements matched '{selector}'."

    total = len(matches)
    limit = total if raw_limit == 0 else raw_limit
    lines = [f"Found {total} match(es) for '{selector}' (showing {min(total, limit)}):"]
    for i, node in enumerate(matches[:limit]):
        path = _node_to_path(node, soup)
        markup = _trunc(str(node), tc)
        lines.append(f"\n[{i}] path: {path}")
        lines.append(f"     {markup}")
    return "\n".join(lines)


def _action_list_children(soup, args: dict) -> str:
    from bs4 import Tag

    path = args.get("path") or []
    node, err = _resolve_path(soup, path)
    if err:
        return f"Error: {err}"

    children = [c for c in node.children if isinstance(c, Tag)]
    if not children:
        return f"No element children at {path or 'root'}."

    lines = [f"Element children of {path or 'root'} ({len(children)} total):"]
    for i, child in enumerate(children):
        child_path = _node_to_path(child, soup)
        key_attrs = {
            k: (" ".join(child.get(k)) if isinstance(child.get(k), list) else str(child.get(k)))
            for k in ("id", "class", "href", "src", "type", "name")
            if child.get(k) is not None
        }
        attr_str = f"  {json.dumps(key_attrs)}" if key_attrs else ""
        lines.append(f"  [{i}] {child_path}{attr_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

def execute(
    args: dict,
    session_data: dict | None = None,
    special_resources: dict | None = None,
) -> str:
    if session_data is None:
        session_data = {}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "Error: beautifulsoup4 is not installed."

    memory_key: str = args["memory_key"]
    action: str = args["action"]

    memory = ensure_session_memory(session_data)
    html = memory.get(memory_key)
    if html is None:
        return f"Error: No session memory item found at key '{memory_key}'."
    if not isinstance(html, str):
        html = str(html)
    if not html.strip():
        return f"Error: Session memory item '{memory_key}' is empty."

    on_chunk = (special_resources or {}).get("on_chunk")
    if on_chunk:
        on_chunk(f"Parsing HTML from '{memory_key}'...")

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            return f"Error: Failed to parse HTML: {e}"

    if action == "preview":
        return _action_preview(soup, args)
    if action == "get_node":
        return _action_get_node(soup, args, session_data)
    if action == "get_attribute":
        return _action_get_attribute(soup, args, session_data)
    if action == "find_nodes":
        return _action_find_nodes(soup, args)
    if action == "list_children":
        return _action_list_children(soup, args)
    return f"Error: Unknown action '{action}'."
