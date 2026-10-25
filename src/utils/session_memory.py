from __future__ import annotations

from typing import Any, Callable, Iterator

from src.utils.sql import session_memory_db as _db


class SessionMemory(dict):
    """
    A session's memory: a dict view over its `session_memory` rows in MySQL.

    Every read and write goes straight to MySQL, so the data is never only in
    one process and there is nothing to copy or save later. The underlying
    CPython dict storage is intentionally kept empty; it exists purely so that
    isinstance(x, dict) returns True, maintaining backward compatibility with
    code that checks isinstance(memory, dict) (e.g. the
    _ensure_session_memory helpers scattered across tool files).

    Keys and values must be strings (all memory values are plain text).
    `on_change(key, "modified" | "deleted")` runs after each change.

    Limitations
    -----------
    - dict(instance) and copy.copy(instance) operate on CPython's internal
      dict storage at the C level, bypassing __iter__ / __getitem__, so they
      will produce an empty plain dict.  Use .to_dict() for a full snapshot.
    """

    def __init__(
        self,
        session_id: str,
        on_change: Callable[[str, str], None] | None = None,
    ) -> None:
        # Call super().__init__() with NO data so the internal CPython dict
        # stays empty.  All real storage is in MySQL.
        super().__init__()
        self._session_id = session_id
        self._on_change = on_change

    def _changed(self, key: str, kind: str) -> None:
        if self._on_change:
            self._on_change(key, kind)

    # ------------------------------------------------------------------
    # Core mapping protocol
    # ------------------------------------------------------------------

    def __setitem__(self, key: str, value: str) -> None:
        _db.set_memory_value(self._session_id, key, value)
        self._changed(key, "modified")

    def __getitem__(self, key: str) -> str:
        val = _db.get_memory_value(self._session_id, key)
        if val is None:
            raise KeyError(key)
        return val

    def __delitem__(self, key: str) -> None:
        if not _db.delete_memory_key(self._session_id, key):
            raise KeyError(key)
        self._changed(key, "deleted")

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and _db.has_memory_key(self._session_id, key)

    def __iter__(self) -> Iterator[str]:
        return iter(_db.list_memory_keys(self._session_id))

    def __len__(self) -> int:
        return _db.count_memory_keys(self._session_id)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_dict()!r})"

    # ------------------------------------------------------------------
    # dict methods that operate on CPython's internal storage at the C
    # level and therefore MUST be overridden to route through MySQL.
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        val = _db.get_memory_value(self._session_id, key)
        return val if val is not None else default

    def keys(self) -> list[str]:  # type: ignore[override]
        return _db.list_memory_keys(self._session_id)

    def values(self) -> list[str]:  # type: ignore[override]
        return list(self.to_dict().values())

    def items(self) -> list[tuple[str, str]]:  # type: ignore[override]
        return list(self.to_dict().items())

    def pop(self, key: str, *args: Any) -> Any:
        val = _db.get_memory_value(self._session_id, key)
        if val is None or not _db.delete_memory_key(self._session_id, key):
            if args:
                return args[0]
            raise KeyError(key)
        self._changed(key, "deleted")
        return val

    def setdefault(self, key: str, default: str = "") -> str:  # type: ignore[override]
        # INSERT IGNORE is atomic: sets only if the key does not already exist.
        if _db.add_memory_value(self._session_id, key, default):
            self._changed(key, "modified")
        return _db.get_memory_value(self._session_id, key)  # type: ignore[return-value]

    def update(self, other: Any = None, **kwargs: str) -> None:  # type: ignore[override]
        if other is not None:
            pairs = other.items() if hasattr(other, "items") else other
            for k, v in pairs:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def clear(self) -> None:
        keys = _db.list_memory_keys(self._session_id)
        _db.clear_memory(self._session_id)
        for key in keys:
            self._changed(key, "deleted")

    def copy(self) -> dict[str, str]:  # type: ignore[override]
        """Return a plain dict snapshot.  The result is NOT a SessionMemory."""
        return self.to_dict()

    # ------------------------------------------------------------------
    # Extras
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, str]:
        """Return a plain dict snapshot of all current key-value pairs."""
        return _db.load_memory(self._session_id)
