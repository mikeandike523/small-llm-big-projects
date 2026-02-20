from __future__ import annotations

import json
import os
from pathlib import Path

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

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
                        "If true, annotate each entry with its resolved kind (text format only). "
                        "Has no effect when format='json'. Default: false."
                    ),
                },
                "depth": {
                    "type": "integer",
                    "description": (
                        "Maximum recursion depth. depth=0 means immediate children only; "
                        "null means unlimited. Only meaningful when recursive=true. Default: null."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["text", "json"],
                    "description": "Output format: 'text' for human-readable, 'json' for structured JSON. Default: 'text'.",
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
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "Where to send the result. "
                        "'return_value' (default) returns the result directly. "
                        "'session_memory' writes to a session memory key. "
                        "'project_memory' writes to a project memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the result to. "
                        "Required when target is 'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Gitignore helpers
# ---------------------------------------------------------------------------

def _find_gitignore_root(path: str) -> Path:
    """Walk up from path looking for a .git entry; stop at drive root."""
    p = Path(path).resolve()
    while True:
        if (p / ".git").exists():
            return p
        parent = p.parent
        if parent == p:  # reached drive root
            return p
        p = parent


def _get_ancestor_matchers(gitignore_root: Path, path: str) -> list:
    """
    Walk DOWN from gitignore_root to path (exclusive), collecting matchers
    for any .gitignore files encountered along the way.
    """
    try:
        from gitignore_parser import parse_gitignore
    except ImportError:
        return []

    target = Path(path).resolve()
    try:
        rel = target.relative_to(gitignore_root)
    except ValueError:
        return []

    matchers: list = []
    current = gitignore_root
    for part in rel.parts:
        gi_file = current / ".gitignore"
        if gi_file.exists():
            try:
                matchers.append(parse_gitignore(str(gi_file)))
            except Exception:
                pass
        current = current / part

    return matchers


def _get_effective_matchers(dir_path: str, parent_matchers: list, use_gitignore: bool) -> list:
    """
    Return parent_matchers plus a new matcher for dir_path/.gitignore if it exists.
    Returns parent_matchers unchanged when use_gitignore=False.
    """
    if not use_gitignore:
        return parent_matchers

    try:
        from gitignore_parser import parse_gitignore
    except ImportError:
        return parent_matchers

    gi_file = Path(dir_path) / ".gitignore"
    if gi_file.exists():
        try:
            return parent_matchers + [parse_gitignore(str(gi_file))]
        except Exception:
            pass
    return parent_matchers


def _is_ignored(abs_path: str, matchers: list) -> bool:
    return any(m(abs_path) for m in matchers)


# ---------------------------------------------------------------------------
# Symlink helpers
# ---------------------------------------------------------------------------

def _read_link_safe(path: str) -> str:
    try:
        return os.readlink(path)
    except (OSError, ValueError):
        return ""


def _follow_file_symlink(path: str):
    """
    Follow a file symlink chain until a real file or a loop is detected.

    Returns:
        ("file", None)          — clean chain, resolved to a real file
        ("link", raw_target)    — loop detected; raw_target is os.readlink(current)
                                  at the last node before the loop
    """
    try:
        chain_seen = {os.path.realpath(path)}
        current = path

        while True:
            try:
                target = os.readlink(current)
            except (OSError, ValueError):
                return "link", _read_link_safe(current)

            target_real = os.path.realpath(target)

            if target_real in chain_seen:
                # Loop detected — current is the last node before the loop
                return "link", target  # raw readlink of current

            if os.path.islink(target):
                chain_seen.add(target_real)
                current = target
                continue
            else:
                # Reached a real file
                return "file", None

    except (OSError, ValueError):
        return "link", _read_link_safe(path)


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------

def _traverse(
    dir_path: str,
    recursive: bool,
    follow_folder_symlinks: bool,
    follow_file_symlinks: bool,
    depth,           # int | None
    visited_dirs: set,
    matchers: list,
    use_gitignore: bool,
) -> list:
    """
    Scan dir_path and return a list of entry dicts.

    Entry dict fields:
        name         (str)
        type         ("file" | "folder" | "link")
        link_target  (str, only for type="link")
        children     (list, only for folders and followed dir symlinks)
        _is_dir_link (bool, internal — True for dir symlinks)
        _loop        (bool, internal — True for looped file symlinks)
    """
    entries: list = []

    try:
        scan_entries = sorted(os.scandir(dir_path), key=lambda e: e.name)
    except (OSError, PermissionError):
        return entries

    for entry in scan_entries:
        try:
            is_link = entry.is_symlink()
            is_dir = entry.is_dir(follow_symlinks=False)
        except (OSError, PermissionError):
            continue

        abs_path = os.path.abspath(entry.path)

        # When respecting gitignores, always skip .git directories
        if use_gitignore and is_dir and entry.name == ".git":
            continue

        # Gitignore check (before any other processing for performance)
        if use_gitignore and matchers:
            if _is_ignored(abs_path, matchers):
                continue

        if is_dir:
            if is_link:
                # Directory symlink / junction
                link_target = _read_link_safe(entry.path)

                if not follow_folder_symlinks:
                    entries.append({
                        "name": entry.name,
                        "type": "link",
                        "link_target": link_target,
                        "_is_dir_link": True,
                    })
                else:
                    real = os.path.realpath(entry.path)
                    if real in visited_dirs:
                        continue  # loop protection — skip silently
                    visited_dirs.add(real)

                    children: list = []
                    if recursive and (depth is None or depth > 0):
                        new_depth = (depth - 1) if depth is not None else None
                        child_matchers = _get_effective_matchers(entry.path, matchers, use_gitignore)
                        children = _traverse(
                            dir_path=entry.path,
                            recursive=recursive,
                            follow_folder_symlinks=follow_folder_symlinks,
                            follow_file_symlinks=follow_file_symlinks,
                            depth=new_depth,
                            visited_dirs=visited_dirs,
                            matchers=child_matchers,
                            use_gitignore=use_gitignore,
                        )
                    entries.append({
                        "name": entry.name,
                        "type": "link",
                        "link_target": link_target,
                        "_is_dir_link": True,
                        "children": children,
                    })

            else:
                # Regular directory
                real = os.path.realpath(entry.path)
                if real in visited_dirs:
                    continue  # loop protection
                visited_dirs.add(real)

                children = []
                if recursive and (depth is None or depth > 0):
                    new_depth = (depth - 1) if depth is not None else None
                    child_matchers = _get_effective_matchers(entry.path, matchers, use_gitignore)
                    children = _traverse(
                        dir_path=entry.path,
                        recursive=recursive,
                        follow_folder_symlinks=follow_folder_symlinks,
                        follow_file_symlinks=follow_file_symlinks,
                        depth=new_depth,
                        visited_dirs=visited_dirs,
                        matchers=child_matchers,
                        use_gitignore=use_gitignore,
                    )
                entries.append({
                    "name": entry.name,
                    "type": "folder",
                    "children": children,
                })

        else:
            # File (possibly symlinked)
            if is_link:
                link_target = _read_link_safe(entry.path)

                if not follow_file_symlinks:
                    entries.append({
                        "name": entry.name,
                        "type": "link",
                        "link_target": link_target,
                    })
                else:
                    result_type, loop_target = _follow_file_symlink(entry.path)
                    if result_type == "file":
                        entries.append({
                            "name": entry.name,
                            "type": "file",
                        })
                    else:
                        # Looped file symlink
                        entries.append({
                            "name": entry.name,
                            "type": "link",
                            "link_target": loop_target,
                            "_loop": True,
                        })
            else:
                # Regular file
                entries.append({
                    "name": entry.name,
                    "type": "file",
                })

    return entries


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
        if show_data:
            lines.append(f"{prefix}{name}/ (folder)")
        else:
            lines.append(f"{prefix}{name}/")
    elif etype == "file":
        if show_data:
            lines.append(f"{prefix}{name} (file)")
        else:
            lines.append(f"{prefix}{name}")
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


def _collect_flat(children: list, parent_path: str, filter_mode: str, results: list) -> None:
    """
    Recursively collect entries matching filter_mode into results as (rel_path, entry) tuples.
    parent_path uses forward slashes and is the path prefix for this level.
    """
    for entry in children:
        name = entry["name"]
        rel_path = f"{parent_path}/{name}" if parent_path else name
        etype = entry["type"]
        is_dir_link = entry.get("_is_dir_link", False)

        if filter_mode == "files":
            if etype == "file":
                results.append((rel_path, entry))
            elif etype == "link" and not is_dir_link:
                # File symlink (unfollowed or looped)
                results.append((rel_path, entry))
        elif filter_mode == "folders":
            if etype == "folder":
                results.append((rel_path, entry))
            elif etype == "link" and is_dir_link:
                # Dir symlink (followed or unfollowed)
                results.append((rel_path, entry))

        # Always recurse into children (filter affects output, not traversal)
        if "children" in entry:
            _collect_flat(entry["children"], rel_path, filter_mode, results)


def _text_annotation(entry: dict) -> str:
    etype = entry["type"]
    is_loop = entry.get("_loop", False)
    link_target = entry.get("link_target", "")

    if etype == "file":
        return "file"
    elif etype == "folder":
        return "folder"
    elif etype == "link":
        if is_loop:
            return "link"
        else:
            return f"link -> {link_target}"
    return ""


def _format_text(root_entry: dict, filter_mode: str, show_data: bool) -> str:
    if filter_mode == "both":
        # Mode A: indented tree view starting at root
        lines = _tree_lines(root_entry, indent=0, show_data=show_data)
        return "\n".join(lines)
    else:
        # Mode B: flat list of relative paths
        flat: list = []
        _collect_flat(root_entry.get("children", []), "", filter_mode, flat)
        if show_data:
            lines = [f"{rel_path} ({_text_annotation(entry)})" for rel_path, entry in flat]
        else:
            lines = [rel_path for rel_path, entry in flat]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON formatting
# ---------------------------------------------------------------------------

def _clean_for_json_mode_a(entry: dict) -> dict:
    """Strip internal fields and produce a clean JSON-serialisable entry dict."""
    cleaned: dict = {"name": entry["name"], "type": entry["type"]}
    if "link_target" in entry:
        cleaned["link_target"] = entry["link_target"]
    if "children" in entry:
        cleaned["children"] = [_clean_for_json_mode_a(c) for c in entry["children"]]
    return cleaned


def _format_json(root_entry: dict, filter_mode: str) -> str:
    if filter_mode == "both":
        # Mode A: single root object with nested children
        cleaned = _clean_for_json_mode_a(root_entry)
        return json.dumps(cleaned, indent=2)
    else:
        # Mode B: flat array with "path" field
        flat: list = []
        _collect_flat(root_entry.get("children", []), "", filter_mode, flat)

        json_entries: list = []
        for rel_path, entry in flat:
            obj: dict = {
                "path": rel_path.replace("\\", "/"),
                "type": entry["type"],
            }
            if "link_target" in entry:
                obj["link_target"] = entry["link_target"]
            json_entries.append(obj)

        return json.dumps(json_entries, indent=2)


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
    fmt = args.get("format", "text")
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
    children = _traverse(
        dir_path=path,
        recursive=recursive,
        follow_folder_symlinks=follow_folder_symlinks,
        follow_file_symlinks=follow_file_symlinks,
        depth=depth,
        visited_dirs=visited_dirs,
        matchers=effective_matchers,
        use_gitignore=use_gitignore,
    )

    root_name = Path(path).name or path
    root_entry: dict = {
        "name": root_name,
        "type": "folder",
        "children": children,
    }

    # --- Format ---
    if fmt == "json":
        result_str = _format_json(root_entry, filter_mode)
    else:
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

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, result_str)
            conn.commit()
        return f"Directory listing written to project memory key {memory_key!r}."

    return result_str
