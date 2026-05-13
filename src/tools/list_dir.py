from __future__ import annotations

import os
import time
from pathlib import Path

from src.tools._list_dir_utils import (
    _find_gitignore_root,
    _get_ancestor_matchers,
    _get_effective_matchers,
    _traverse,
    _collect_flat,
)

DEFAULT_TIMEOUT = 30  # seconds
TIMEOUT_HINT = "list_dir timed out; consider restricting traversal depth (use the 'depth' parameter)"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": (
            "List the contents of a directory with configurable recursion, "
            "symlink handling, filtering, and type annotation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "The directory to list. Accepts relative (resolved from cwd) "
                        "or absolute paths. Default: current working directory."
                    ),
                },
                "recursive": {
                    "type": "boolean",
                    "description": "If true, descend into subdirectories. Default: false.",
                },
                "follow_folder_symlinks": {
                    "type": "boolean",
                    "description": (
                        "If true, recurse into symlinks that point to directories. "
                        "Only meaningful when recursive=true. Default: false."
                    ),
                },
                "follow_file_symlinks": {
                    "type": "boolean",
                    "description": (
                        "If true, follow file symlinks to their final destination. "
                        "Chains are followed repeatedly. Default: false."
                    ),
                },
                "filter": {
                    "type": "string",
                    "enum": ["files", "folders", "both"],
                    "description": (
                        "Controls which entry types appear in output. "
                        "Filtering affects output only, not traversal. Default: 'both'."
                    ),
                },
                "show_data": {
                    "type": "boolean",
                    "description": (
                        "If true, annotate each entry with its resolved kind. "
                        "Default: false."
                    ),
                },
                "depth": {
                    "type": "integer",
                    "description": (
                        "Maximum recursion depth. depth=0 means immediate children only; "
                        "null means unlimited. Only meaningful when recursive=true. Default: null."
                    ),
                },
                "use_gitignore": {
                    "type": "boolean",
                    "description": (
                        "If true, parse and apply .gitignore rules during traversal. "
                        "Ignored entries are excluded and ignored directories are not descended into. "
                        "The .git directory is always excluded when this is enabled. "
                        "Default: false."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "Where to send the result. "
                        "'return_value' (default) returns the result directly. "
                        "'session_memory' writes to a session memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the result to. "
                        "Required when target is 'session_memory'."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval

    return needs_path_approval(args.get("path"))


# ---------------------------------------------------------------------------
# Gitignore helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Symlink helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------


def _tree_lines(entry: dict, indent: int, show_data: bool) -> list[str]:
    """Recursively build indented tree lines for Mode A text output."""
    prefix = "  " * indent
    lines: list[str] = []
    name = entry["name"]
    etype = entry["type"]
    is_loop = entry.get("_loop", False)
    link_target = entry.get("link_target")

    if etype == "folder":
        lines.append(f"{prefix}{name}/" + (" (folder)" if show_data else ""))
    elif etype == "file":
        lines.append(f"{prefix}{name}" + (" (file)" if show_data else ""))
    elif etype == "link":
        if show_data:
            if is_loop:
                lines.append(f"{prefix}{name} (link)")
            elif link_target is not None:
                lines.append(f"{prefix}{name} (link -> {link_target})")
            else:
                lines.append(f"{prefix}{name}")
        else:
            lines.append(f"{prefix}{name}")

    # Recurse into children (folders and followed dir symlinks)
    for child in entry.get("children", []):
        lines.extend(_tree_lines(child, indent + 1, show_data))

    return lines


def _text_annotation(entry: dict) -> str:
    etype = entry["type"]
    is_loop = entry.get("_loop", False)
    link_target = entry.get("link_target", "")

    if etype == "file":
        return "file"
    if etype == "folder":
        return "folder"
    if etype == "link":
        if is_loop:
            return "link"
        return f"link -> {link_target}"
    return ""


def _format_text(root_entry: dict, filter_mode: str, show_data: bool) -> str:
    if filter_mode == "both":
        # Mode A: indented tree view starting at CHILDREN (omit root itself)
        lines: list[str] = []
        for child in root_entry.get("children", []):
            lines.extend(_tree_lines(child, indent=0, show_data=show_data))
        return "\n".join(lines)

    # Mode B: flat list of relative paths
    flat: list = []
    _collect_flat(root_entry.get("children", []), "", filter_mode, flat)
    if show_data:
        lines = [f"{rel_path} ({_text_annotation(entry)})" for rel_path, entry in flat]
    else:
        lines = [rel_path for rel_path, _entry in flat]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session memory helper
# ---------------------------------------------------------------------------


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def execute(args: dict, session_data: dict) -> str:
    # --- Parse args ---
    raw_path = args.get("path", os.getcwd())
    path = os.path.abspath(raw_path)

    recursive = bool(args.get("recursive", False))
    follow_folder_symlinks = bool(args.get("follow_folder_symlinks", False))
    follow_file_symlinks = bool(args.get("follow_file_symlinks", False))
    filter_mode = args.get("filter", "both")
    show_data = bool(args.get("show_data", False))
    depth = args.get("depth", None)  # int | None
    use_gitignore = bool(args.get("use_gitignore", False))
    target = args.get("target", "return_value")
    memory_key = args.get("memory_key")

    if not os.path.isdir(path):
        return f"Error: {path!r} is not a directory."

    # --- Initialise gitignore matchers ---
    ancestor_matchers: list = []
    if use_gitignore:
        gitignore_root = _find_gitignore_root(path)
        ancestor_matchers = _get_ancestor_matchers(gitignore_root, path)

    # Effective matchers for the root directory itself
    effective_matchers = _get_effective_matchers(path, ancestor_matchers, use_gitignore)

    # --- Initialise visited_dirs with the root ---
    visited_dirs: set = {os.path.realpath(path)}

    # --- Traverse ---
    _start_time = time.monotonic()
    children = _traverse(
        dir_path=path,
        recursive=recursive,
        follow_folder_symlinks=follow_folder_symlinks,
        follow_file_symlinks=follow_file_symlinks,
        depth=depth,
        visited_dirs=visited_dirs,
        matchers=effective_matchers,
        use_gitignore=use_gitignore,
        start_time=_start_time,
        timeout=DEFAULT_TIMEOUT,
        timeout_hint=TIMEOUT_HINT,
    )

    root_name = Path(path).name or path
    root_entry: dict = {
        "name": root_name,
        "type": "folder",
        "children": children,
    }

    # --- Format (text only) ---
    result_str = _format_text(root_entry, filter_mode, show_data)

    # --- Deliver ---
    if target == "return_value":
        return result_str

    if target == "session_memory":
        if session_data is None:
            session_data = {}
        memory = _ensure_session_memory(session_data)
        memory[memory_key] = result_str
        return f"Directory listing written to session memory key {memory_key!r}."

    return result_str
