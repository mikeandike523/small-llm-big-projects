from __future__ import annotations
import os

_dirty_files: dict[str, set[str]] = {}  # session_id -> set[normalized abs path]
_dirty_mem: dict[str, set[str]] = {}    # session_id -> set[mem key]
_seen_files: dict[str, set[str]] = {}   # session_id -> set[normalized abs path] (read at least once)
_seen_mem: dict[str, set[str]] = {}     # session_id -> set[mem key] (read at least once)


def _norm(path: str, cwd: str | None = None) -> str:
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
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


def is_file_dirty(session_id: str, path: str, cwd: str | None = None) -> bool:
    return _norm(path, cwd) in _files(session_id)


def has_file_been_seen(session_id: str, path: str, cwd: str | None = None) -> bool:
    return _norm(path, cwd) in _seen_f(session_id)


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


def _display_path(norm_path: str, cwd: str | None) -> str:
    """Return a relative path if norm_path is under cwd, else return norm_path as-is.

    Ideally we would surface the exact string the LLM passed in its arguments,
    so the hint exactly mirrors what the agent wrote. That would require each
    dirty_effects() function to annotate which argument keys are the path
    sources, so check_requires_clean could look them up in the original args.
    For now, relativising against the session CWD is a decent interim: it avoids
    nudging the agent toward absolute paths, even though it still loses the
    original casing.
    """
    if cwd:
        norm_cwd = _norm(cwd)
        try:
            rel = os.path.relpath(norm_path, norm_cwd)
            if not rel.startswith(".."):
                return rel
        except ValueError:
            pass
    return norm_path


def check_requires_clean(
    session_id: str,
    effects: dict,
    tool_name: str,
    cwd: str | None = None,
    strict: bool = True,
) -> str | None:
    """Return an error string if any required-clean resource is unseen or dirty, else None.

    When strict=False, only resources that have never been read are blocked;
    resources that are dirty (modified since last read) are allowed through.
    """
    unseen_files = [
        _norm(p, cwd)
        for p in effects.get("requires_clean_files", [])
        if not has_file_been_seen(session_id, p, cwd)
    ]
    dirty_files = (
        [
            _norm(p, cwd)
            for p in effects.get("requires_clean_files", [])
            if has_file_been_seen(session_id, p, cwd) and is_file_dirty(session_id, p, cwd)
        ]
        if strict
        else []
    )
    unseen_mem = [
        k for k in effects.get("requires_clean_mem", [])
        if not has_mem_been_seen(session_id, k)
    ]
    dirty_mem = (
        [
            k for k in effects.get("requires_clean_mem", [])
            if has_mem_been_seen(session_id, k) and is_mem_dirty(session_id, k)
        ]
        if strict
        else []
    )

    if not unseen_files and not dirty_files and not unseen_mem and not dirty_mem:
        return None

    # These notes exist because of a specific failure mode seen in testing with
    # smaller models: when told a file/mem key is dirty or unseen, they routinely
    # reach for the plausible-looking wrong fix instead of the one that actually
    # clears the flag, then loop on the same error. Files and mem keys are tracked
    # in two completely independent namespaces (see module docstring/sets above),
    # so touching one never clears the other -- the model has to be told that
    # explicitly or it assumes it does. Concretely:
    #   - for a dirty/unseen FILE, the model tends to call
    #     read_text_file(path=..., session_memory_key=...) -- which dirties a mem
    #     key and does nothing to clean the file -- or picks at it with line_reader,
    #     whose partial-read dirty_effects are deliberately disabled (see
    #     line_reader.py) so it never clears this state either.
    #   - for a dirty/unseen MEM key, the model tends to re-read the underlying
    #     file from disk, assuming that refreshes the key it actually needs to write.
    _FILE_NOTE = (
        "    Note: reading into a session memory key (session_memory_key=...), or a "
        "partial read via line_reader, will NOT clear this -- only a full "
        "read_text_file(path=...) call (no session_memory_key) counts."
    )
    _MEM_NOTE = (
        "    Note: reading a related file on disk will NOT clear this -- the memory "
        "item itself must be read directly with session_memory(action='get', key=...)."
    )

    lines = [f"Error: '{tool_name}' blocked:"]
    for p in unseen_files:
        dp = _display_path(p, cwd)
        lines.append(f"  File '{dp}' has not been read yet. Your context may be incorrect.")
        lines.append(f"    Run this exact command: read_text_file(path='{dp}')")
        lines.append(_FILE_NOTE)
    for p in dirty_files:
        dp = _display_path(p, cwd)
        lines.append(f"  File '{dp}' is dirty (modified since last read). Your context may be out of date.")
        lines.append(f"    Re-read with this exact command: read_text_file(path='{dp}')")
        lines.append(_FILE_NOTE)
    for k in unseen_mem:
        lines.append(f"  Memory item '{k}' has not been read yet. Your context may be incorrect.")
        lines.append(f"    Run this exact command: session_memory(action='get', key='{k}')")
        lines.append(_MEM_NOTE)
    for k in dirty_mem:
        lines.append(f"  Memory item '{k}' is dirty (modified since last read). Your context may be incorrect.")
        lines.append(f"    Re-read with this exact command: session_memory(action='get', key='{k}')")
        lines.append(_MEM_NOTE)
    return "\n".join(lines)


def apply_effects(session_id: str, effects: dict, cwd: str | None = None) -> bool:
    """Apply dirty/clean/seen effects. Returns True if any state changed."""
    changed = False
    for p in effects.get("cleans_files", []):
        n = _norm(p, cwd)
        if n in _files(session_id):
            _files(session_id).discard(n)
            changed = True
        if n not in _seen_f(session_id):
            _seen_f(session_id).add(n)
            changed = True
    for p in effects.get("dirties_files", []):
        n = _norm(p, cwd)
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
