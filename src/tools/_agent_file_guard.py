"""Protecting an agent's workspace files while its sessions run in parallel.

Only sessions in an agent's pool have an ``agent_file_scope``; for every other
session nothing here does anything. Three rules apply inside the workspace:

- **Always allowed:** the agent's SOUL.md and MEMORY.md and the current sender's
  MEMORY.md need no approval from the file tools, whatever the approval mode.
- **Advisory lock:** one write at a time per file. The lock is held only for the
  check-write-record below, never during an approval wait, so a hung session
  cannot block the others. Shell tools can bypass it: it is advisory.
- **Version check:** a write is refused if the file changed since this session
  last read it through the matching route. A full read returned to the agent
  covers raw text writes and on-disk patches, because the agent has that text in
  context. A full read into a memory key covers writes from that key only. So
  reading into memory never makes a raw write look safe, or the other way round.

Versions are hashes of the raw file bytes, because the text a read returns can
be redacted or have its line endings changed. They live only in this process:
after a restart the agent just has to read again.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.tools._path_utils import _resolve_path
from src.utils.agent_dirs import MEMORY_FILE, SOUL_FILE, get_agent_workspace
from src.utils.agent_store import get_agent

READ_LOCK_WAIT_SECONDS = 5.0
_FAILED_PREFIXES = ("Error", "Failed", "TIMEOUT", "HANG")

# The path argument of each file tool that may touch an always-allowed file.
_ALWAYS_ALLOWED_TOOL_ARGS = {
    "read_text_file": "path",
    "line_reader": "path",
    "write_text_file": "path",
    "create_text_file": "path",
    "text_editor": "filepath",
}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


@dataclass(frozen=True)
class AgentFileScope:
    workspace: str
    always_allowed: frozenset[str]

    def contains(self, normalized_path: str) -> bool:
        return normalized_path.startswith(self.workspace + os.sep)


def make_scope(workspace: str, user_dir: str) -> AgentFileScope:
    return AgentFileScope(
        workspace=_norm(workspace),
        always_allowed=frozenset(
            _norm(path)
            for path in (
                os.path.join(workspace, SOUL_FILE),
                os.path.join(workspace, MEMORY_FILE),
                os.path.join(user_dir, MEMORY_FILE),
            )
        ),
    )


def scope_for_session(
    agent_id: str | None, initial_cwd: str | None
) -> AgentFileScope | None:
    """The session's scope (its starting folder is the sender's folder)."""
    if agent_id is None or not initial_cwd:
        return None
    agent = get_agent(agent_id)
    if agent is None:
        return None
    return make_scope(get_agent_workspace(agent.slug), initial_cwd)


def _cwd(special_resources: dict) -> str | None:
    return special_resources.get("session_current_working_dir")


def is_always_allowed(
    tool_name: str, args: dict, special_resources: dict | None
) -> bool:
    """True when this call needs no approval because of the file it touches."""
    scope = (special_resources or {}).get("agent_file_scope")
    arg_name = _ALWAYS_ALLOWED_TOOL_ARGS.get(tool_name)
    if scope is None or arg_name is None:
        return False
    path = args.get(arg_name)
    if not isinstance(path, str) or not path:
        return False
    resolved = _resolve_path(path, _cwd(special_resources))
    # A link named MEMORY.md must not turn into unapproved access elsewhere.
    if os.path.islink(resolved):
        return False
    return _norm(resolved) in scope.always_allowed


# -- known versions ----------------------------------------------------------


@dataclass
class _KnownVersions:
    context: dict[str, str] = field(default_factory=dict)
    # memory key -> (normalized path of the file it was read from, its version)
    keys: dict[str, tuple[str, str]] = field(default_factory=dict)


_state_lock = threading.Lock()
_known_by_session: dict[str, _KnownVersions] = {}
_path_locks: dict[str, threading.Lock] = {}


def _known(session_id: str) -> _KnownVersions:
    with _state_lock:
        return _known_by_session.setdefault(session_id, _KnownVersions())


def clear_session(session_id: str) -> None:
    with _state_lock:
        _known_by_session.pop(session_id, None)


def _path_lock(path: str) -> threading.Lock:
    with _state_lock:
        return _path_locks.setdefault(path, threading.Lock())


def _acquire(paths: list[str], *, wait_seconds: float = 0.0) -> list[threading.Lock]:
    """Every path's lock, in sorted order, or [] and none held. ``paths`` is
    never empty, so [] always means another session holds one."""
    held: list[threading.Lock] = []
    deadline = time.monotonic() + wait_seconds
    for path in sorted(set(paths)):
        lock = _path_lock(path)
        remaining = deadline - time.monotonic()
        acquired = (
            lock.acquire(timeout=remaining) if remaining > 0 else lock.acquire(False)
        )
        if not acquired:
            for other in held:
                other.release()
            return []
        held.append(lock)
    return held


def _digest(path: str) -> str | None:
    """The file's version, or None if it does not exist or cannot be read."""
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def _succeeded(result: Any) -> bool:
    return not (isinstance(result, str) and result.startswith(_FAILED_PREFIXES))


def _locked_error(display: str) -> str:
    return (
        f"Error: File is under advisory lock, please wait and try again: {display}\n"
        "  Another session is using this file. Use the sleep tool for a few "
        "seconds, then retry."
    )


def _stale_context_error(tool_name: str, display: str) -> str:
    return (
        f"Error: '{tool_name}' blocked: '{display}' changed since you last read it, "
        "or you have not read it in full yet.\n"
        f"  Run this exact command: read_text_file(path='{display}')\n"
        "  Then reapply your edit to what you read.\n"
        "  Note: reading into a session memory key, or a partial read, will NOT "
        "clear this."
    )


def _stale_key_error(tool_name: str, display: str, key: str) -> str:
    return (
        f"Error: '{tool_name}' blocked: memory key '{key}' does not hold the current "
        f"version of '{display}'.\n"
        f"  Run this exact command: read_text_file(path='{display}', "
        f"session_memory_key='{key}')\n"
        "  Then reapply your edit to that key. This replaces the key's text.\n"
        "  Note: reading the file without session_memory_key will NOT clear this."
    )


# -- the tools ---------------------------------------------------------------


@dataclass(frozen=True)
class _Call:
    tool_name: str
    args: dict
    special_resources: dict
    scope: AgentFileScope
    run: Callable[[], Any]

    @property
    def known(self) -> _KnownVersions:
        return _known(self.special_resources.get("session_id") or "")

    def target(self, arg_name: str) -> str | None:
        """The argument's normalized path, if it is inside the workspace."""
        raw = self.args.get(arg_name)
        if not isinstance(raw, str) or not raw:
            return None
        normalized = _norm(_resolve_path(raw, _cwd(self.special_resources)))
        return normalized if self.scope.contains(normalized) else None

    def context_error(self, path: str, display: str) -> str | None:
        """Refuse changing an existing file this session has not read as it is."""
        current = _digest(path)
        if current is not None and self.known.context.get(path) != current:
            return _stale_context_error(self.tool_name, display)
        return None


def _guard_read(call: _Call) -> Any:
    path = call.target("path")
    if path is None:
        return call.run()
    held = _acquire([path], wait_seconds=READ_LOCK_WAIT_SECONDS)
    if not held:
        return _locked_error(call.args["path"])
    try:
        version = _digest(path)
        result = call.run()
        if version is not None and _succeeded(result):
            key = call.args.get("session_memory_key")
            if key is not None:
                call.known.keys[key] = (path, version)
            else:
                call.known.context[path] = version
        return result
    finally:
        for lock in held:
            lock.release()


def _guard_write(call: _Call) -> Any:
    path = call.target("path")
    if path is None:
        return call.run()
    display = call.args["path"]
    key = call.args.get("session_memory_key")
    held = _acquire([path])
    if not held:
        return _locked_error(display)
    try:
        current = _digest(path)
        if key is not None:
            if current is not None and call.known.keys.get(key) != (path, current):
                return _stale_key_error(call.tool_name, display, key)
        elif current is not None and call.known.context.get(path) != current:
            return _stale_context_error(call.tool_name, display)
        result = call.run()
        if _succeeded(result):
            version = _digest(path)
            if version is not None:
                if key is not None:
                    call.known.keys[key] = (path, version)
                else:
                    call.known.context[path] = version
        return result
    finally:
        for lock in held:
            lock.release()


def _guard_create(call: _Call) -> Any:
    path = call.target("path")
    if path is None:
        return call.run()
    held = _acquire([path])
    if not held:
        return _locked_error(call.args["path"])
    try:
        result = call.run()
        if _succeeded(result):
            version = _digest(path)
            if version is not None:
                call.known.context[path] = version
        return result
    finally:
        for lock in held:
            lock.release()


def _guard_text_editor(call: _Call) -> Any:
    # Imported here: src.tools imports this module before it imports the tools.
    from src.tools.text_editor import _WRITE_ACTIONS_SET

    path = call.target("filepath")
    if path is None or call.args.get("action") not in _WRITE_ACTIONS_SET:
        return call.run()
    display = call.args["filepath"]
    held = _acquire([path])
    if not held:
        return _locked_error(display)
    try:
        error = call.context_error(path, display)
        if error is not None:
            return error
        result = call.run()
        if _succeeded(result):
            version = _digest(path)
            if version is not None:
                call.known.context[path] = version
        return result
    finally:
        for lock in held:
            lock.release()


def _guard_change(call: _Call, arg_names: tuple[str, ...]) -> Any:
    """Tools that replace or remove a file without the agent seeing the result,
    so the versions are left to go stale and the next write asks for a read."""
    targets = [(name, call.target(name)) for name in arg_names]
    targets = [(name, path) for name, path in targets if path is not None]
    if not targets:
        return call.run()
    held = _acquire([path for _, path in targets])
    if not held:
        return _locked_error(call.args[targets[0][0]])
    try:
        for name, path in targets:
            error = call.context_error(path, call.args[name])
            if error is not None:
                return error
        return call.run()
    finally:
        for lock in held:
            lock.release()


def _guard_restore(call: _Call) -> Any:
    if call.args.get("action", "restore") != "restore":
        return call.run()
    return _guard_change(call, ("path",))


_GUARDS: dict[str, Callable[[_Call], Any]] = {
    "read_text_file": _guard_read,
    "write_text_file": _guard_write,
    "create_text_file": _guard_create,
    "text_editor": _guard_text_editor,
    "restore_file": _guard_restore,
    "delete_file": lambda call: _guard_change(call, ("path",)),
    "copy_file": lambda call: _guard_change(call, ("dst",)),
    "move_dir_or_file": lambda call: _guard_change(call, ("src", "dst")),
}


def guarded_call(
    tool_name: str,
    args: dict,
    special_resources: dict | None,
    run: Callable[[], Any],
) -> Any:
    """Run one tool call under the rules above, if they apply to it."""
    scope = (special_resources or {}).get("agent_file_scope")
    guard = _GUARDS.get(tool_name)
    if scope is None or guard is None:
        return run()
    return guard(_Call(tool_name, args, special_resources, scope, run))
