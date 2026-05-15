from __future__ import annotations
import os

_dirty_files: dict[str, set[str]] = {}  # session_id -> set[normalized abs path]
_dirty_mem: dict[str, set[str]] = {}    # session_id -> set[mem key]
_seen_files: dict[str, set[str]] = {}   # session_id -> set[normalized abs path] (read at least once)
_seen_mem: dict[str, set[str]] = {}     # session_id -> set[mem key] (read at least once)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _files(session_id: str) -> set[str]:
    return _dirty_files.setdefault(session_id, set())


def _mem(session_id: str) -> set[str]:
    return _dirty_mem.setdefault(session_id, set())


def _seen_f(session_id: str) -> set[str]:
    return _seen_files.setdefault(session_id, set())


def _seen_m(session_id: str) -> set[str]:
    return _seen_mem.setdefault(session_id, set())


def mark_file_dirty(session_id: str, path: str) -> None:
    _files(session_id).add(_norm(path))


def mark_file_clean(session_id: str, path: str) -> None:
    n = _norm(path)
    _files(session_id).discard(n)
    _seen_f(session_id).add(n)


def is_file_dirty(session_id: str, path: str) -> bool:
    return _norm(path) in _files(session_id)


def has_file_been_seen(session_id: str, path: str) -> bool:
    return _norm(path) in _seen_f(session_id)


def mark_mem_dirty(session_id: str, key: str) -> None:
    _mem(session_id).add(key)


def mark_mem_clean(session_id: str, key: str) -> None:
    _mem(session_id).discard(key)
    _seen_m(session_id).add(key)


def is_mem_dirty(session_id: str, key: str) -> bool:
    return key in _mem(session_id)


def has_mem_been_seen(session_id: str, key: str) -> bool:
    return key in _seen_m(session_id)


def clear_session(session_id: str) -> None:
    _dirty_files.pop(session_id, None)
    _dirty_mem.pop(session_id, None)
    _seen_files.pop(session_id, None)
    _seen_mem.pop(session_id, None)


def snapshot(session_id: str) -> dict:
    # Both sets are sent in full so the UI can render dirty/seen tags independently.
    # DirtyTab computes "seen but clean" as seen - dirty client-side.
    return {
        "files": sorted(_files(session_id)),
        "seen_files": sorted(_seen_f(session_id)),
        "mem_keys": sorted(_mem(session_id)),
        "seen_mem_keys": sorted(_seen_m(session_id)),
    }


def check_requires_clean(session_id: str, effects: dict, tool_name: str) -> str | None:
    """Return an error string if any required-clean resource is unseen or dirty, else None."""
    unseen_files = [
        _norm(p)
        for p in effects.get("requires_clean_files", [])
        if not has_file_been_seen(session_id, p)
    ]
    dirty_files = [
        _norm(p)
        for p in effects.get("requires_clean_files", [])
        if has_file_been_seen(session_id, p) and is_file_dirty(session_id, p)
    ]
    unseen_mem = [
        k for k in effects.get("requires_clean_mem", [])
        if not has_mem_been_seen(session_id, k)
    ]
    dirty_mem = [
        k for k in effects.get("requires_clean_mem", [])
        if has_mem_been_seen(session_id, k) and is_mem_dirty(session_id, k)
    ]

    if not unseen_files and not dirty_files and not unseen_mem and not dirty_mem:
        return None

    lines = [f"Error: '{tool_name}' blocked:"]
    for p in unseen_files:
        lines.append(f"  File '{p}' has not been read yet.")
        lines.append(f"    Read first with: read_text_file(path='...', target='return_value')")
    for p in dirty_files:
        lines.append(f"  File '{p}' has been modified since last read.")
        lines.append(f"    Re-read with: read_text_file(path='...', target='return_value')")
    for k in unseen_mem:
        lines.append(f"  Session memory key '{k}' has not been read yet.")
        lines.append(f"    Read first with: session_memory(action='get', key='{k}')")
    for k in dirty_mem:
        lines.append(f"  Session memory key '{k}' has been modified since last read.")
        lines.append(f"    Re-read with: session_memory(action='get', key='{k}')")
    return "\n".join(lines)


def apply_effects(session_id: str, effects: dict) -> bool:
    """Apply dirty/clean/seen effects. Returns True if any state changed."""
    changed = False
    for p in effects.get("cleans_files", []):
        n = _norm(p)
        if n in _files(session_id):
            _files(session_id).discard(n)
            changed = True
        if n not in _seen_f(session_id):
            _seen_f(session_id).add(n)
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
        if k not in _seen_m(session_id):
            _seen_m(session_id).add(k)
            changed = True
    for k in effects.get("dirties_mem", []):
        if k not in _mem(session_id):
            _mem(session_id).add(k)
            changed = True
    return changed
