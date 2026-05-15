from __future__ import annotations
import os

_dirty_files: dict[str, set[str]] = {}  # session_id -> set[normalized abs path]
_dirty_mem: dict[str, set[str]] = {}  # session_id -> set[mem key]


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _files(session_id: str) -> set[str]:
    return _dirty_files.setdefault(session_id, set())


def _mem(session_id: str) -> set[str]:
    return _dirty_mem.setdefault(session_id, set())


def mark_file_dirty(session_id: str, path: str) -> None:
    _files(session_id).add(_norm(path))


def mark_file_clean(session_id: str, path: str) -> None:
    _files(session_id).discard(_norm(path))


def is_file_dirty(session_id: str, path: str) -> bool:
    return _norm(path) in _files(session_id)


def mark_mem_dirty(session_id: str, key: str) -> None:
    _mem(session_id).add(key)


def mark_mem_clean(session_id: str, key: str) -> None:
    _mem(session_id).discard(key)


def is_mem_dirty(session_id: str, key: str) -> bool:
    return key in _mem(session_id)


def clear_session(session_id: str) -> None:
    _dirty_files.pop(session_id, None)
    _dirty_mem.pop(session_id, None)


def snapshot(session_id: str) -> dict:
    return {
        "files": sorted(_files(session_id)),
        "mem_keys": sorted(_mem(session_id)),
    }


def check_requires_clean(session_id: str, effects: dict, tool_name: str) -> str | None:
    """Return an error string if any required-clean resource is dirty, else None."""
    blocked_files = [
        _norm(p)
        for p in effects.get("requires_clean_files", [])
        if is_file_dirty(session_id, p)
    ]
    blocked_mem = [
        k for k in effects.get("requires_clean_mem", []) if is_mem_dirty(session_id, k)
    ]
    if not blocked_files and not blocked_mem:
        return None

    lines = [f"Error: '{tool_name}' blocked -- resource(s) modified since last read:"]
    for p in blocked_files:
        lines.append(f"  File: {p}")
        lines.append(f"    Re-read with: read_text_file(path='...', target='return_value')")
    for k in blocked_mem:
        lines.append(f"  Session memory key: '{k}'")
        lines.append(f"    Re-read with: session_memory(action='get', key='{k}')")
    return "\n".join(lines)


def apply_effects(session_id: str, effects: dict) -> bool:
    """Apply dirty/clean effects. Returns True if any state changed."""
    changed = False
    for p in effects.get("cleans_files", []):
        n = _norm(p)
        if n in _files(session_id):
            _files(session_id).discard(n)
            changed = True
    for p in effects.get("dirties_files", []):
        n = _norm(p)
        if n not in _files(session_id):
            _files(session_id).add(n)
            changed = True
    for k in effects.get("cleans_mem", []):
        if k in _mem(session_id):
            _mem(session_id).discard(k)
            changed = True
    for k in effects.get("dirties_mem", []):
        if k not in _mem(session_id):
            _mem(session_id).add(k)
            changed = True
    return changed
