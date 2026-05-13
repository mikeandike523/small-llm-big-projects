import os
from pathlib import Path
import time

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

def _read_link_safe(path: str) -> str:
    try:
        return os.readlink(path)
    except (OSError, ValueError):
        return ""
    
def _resolve_link_target(current: str, target: str) -> str:
    """Resolve a potentially-relative symlink target against current's directory."""
    if os.path.isabs(target):
        return target
    return os.path.normpath(os.path.join(os.path.dirname(current), target))


    
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
                raw_target = os.readlink(current)
            except (OSError, ValueError):
                return "link", _read_link_safe(current)

            next_path = _resolve_link_target(current, raw_target)
            next_real = os.path.realpath(next_path)

            if next_real in chain_seen:
                # Loop detected — current is the last node before the loop
                return "link", raw_target

            # If next hop is itself a symlink, continue the chain
            if os.path.islink(next_path):
                chain_seen.add(next_real)
                current = next_path
                continue

            # Otherwise we've reached a non-symlink path; classify it
            if os.path.isfile(next_path):
                return "file", None

            # Not a regular file (missing, directory, etc.) — treat as link-ish
            return "link", raw_target

    except (OSError, ValueError):
        return "link", _read_link_safe(path)


def _traverse(
    dir_path: str,
    recursive: bool,
    follow_folder_symlinks: bool,
    follow_file_symlinks: bool,
    depth,  # int | None
    visited_dirs: set,
    matchers: list,
    use_gitignore: bool,
    start_time: float,
    timeout: float,
    timeout_hint: str
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
    if time.monotonic() - start_time > timeout:
        from src.utils.exceptions import ToolTimeoutError
        raise ToolTimeoutError("list_dir", timeout, timeout_hint)

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
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "link",
                            "link_target": link_target,
                            "_is_dir_link": True,
                        }
                    )
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
                            start_time=start_time,
                            timeout=timeout,
                        )
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "link",
                            "link_target": link_target,
                            "_is_dir_link": True,
                            "children": children,
                        }
                    )

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
                        start_time=start_time,
                        timeout=timeout,
                    )
                entries.append(
                    {
                        "name": entry.name,
                        "type": "folder",
                        "children": children,
                    }
                )

        else:
            # File (possibly symlinked)
            if is_link:
                link_target = _read_link_safe(entry.path)

                if not follow_file_symlinks:
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "link",
                            "link_target": link_target,
                        }
                    )
                else:
                    result_type, loop_target = _follow_file_symlink(entry.path)
                    if result_type == "file":
                        entries.append(
                            {
                                "name": entry.name,
                                "type": "file",
                            }
                        )
                    else:
                        # Looped / unresolved file symlink
                        entries.append(
                            {
                                "name": entry.name,
                                "type": "link",
                                "link_target": loop_target,
                                "_loop": True,
                            }
                        )
            else:
                # Regular file
                entries.append(
                    {
                        "name": entry.name,
                        "type": "file",
                    }
                )

    return entries

