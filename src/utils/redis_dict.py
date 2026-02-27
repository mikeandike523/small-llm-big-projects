from __future__ import annotations

from typing import Any, Callable, Iterator

import redis as _redis_module


class RedisDict(dict):
    """
    A dict subclass backed by a Redis hash.

    All reads and writes route through Redis HSET / HGET / HDEL / etc.
    The underlying CPython dict storage is intentionally kept empty; it
    exists purely so that isinstance(x, dict) returns True, maintaining
    backward compatibility with code that checks isinstance(memory, dict)
    (e.g. the _ensure_session_memory helpers scattered across tool files).

    Keys and values must be strings.  This matches the session-memory
    contract (all values are plain text) and the behaviour of redis-py
    when decode_responses=True.

    Limitations
    -----------
    - dict(instance) and copy.copy(instance) operate on CPython's internal
      dict storage at the C level, bypassing __iter__ / __getitem__, so they
      will produce an empty plain dict.  Use .to_dict() for a full snapshot.
    - No TTL management; the caller is responsible for expiry / deletion of
      the underlying hash key.
    """

    def __init__(
        self,
        redis_client: _redis_module.Redis,
        hash_key: str,
        on_change: Callable[[str, str], None] | None = None,
    ) -> None:
        # Call super().__init__() with NO data so the internal CPython dict
        # stays empty.  All real storage goes to Redis.
        super().__init__()
        self._redis = redis_client
        self._hash_key = hash_key
        self._on_change = on_change

    # ------------------------------------------------------------------
    # Core mapping protocol
    # ------------------------------------------------------------------

    def __setitem__(self, key: str, value: str) -> None:
        self._redis.hset(self._hash_key, key, value)
        if self._on_change:
            self._on_change(key, "modified")

    def __getitem__(self, key: str) -> str:
        val = self._redis.hget(self._hash_key, key)
        if val is None:
            raise KeyError(key)
        return val

    def __delitem__(self, key: str) -> None:
        removed = self._redis.hdel(self._hash_key, key)
        if not removed:
            raise KeyError(key)
        if self._on_change:
            self._on_change(key, "deleted")

    def __contains__(self, key: object) -> bool:
        return bool(self._redis.hexists(self._hash_key, key))

    def __iter__(self) -> Iterator[str]:
        return iter(self._redis.hkeys(self._hash_key))

    def __len__(self) -> int:
        return self._redis.hlen(self._hash_key)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._redis.hgetall(self._hash_key)!r})"

    # ------------------------------------------------------------------
    # dict methods that operate on CPython's internal storage at the C
    # level and therefore MUST be overridden to route through Redis.
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        val = self._redis.hget(self._hash_key, key)
        return val if val is not None else default

    def keys(self) -> list[str]:  # type: ignore[override]
        return self._redis.hkeys(self._hash_key)

    def values(self) -> list[str]:  # type: ignore[override]
        return list(self._redis.hgetall(self._hash_key).values())

    def items(self) -> list[tuple[str, str]]:  # type: ignore[override]
        return list(self._redis.hgetall(self._hash_key).items())

    def pop(self, key: str, *args: Any) -> Any:
        val = self._redis.hget(self._hash_key, key)
        if val is None:
            if args:
                return args[0]
            raise KeyError(key)
        self._redis.hdel(self._hash_key, key)
        return val

    def setdefault(self, key: str, default: str = "") -> str:  # type: ignore[override]
        # HSETNX is atomic: sets only if the key does not already exist.
        self._redis.hsetnx(self._hash_key, key, default)
        return self._redis.hget(self._hash_key, key)  # type: ignore[return-value]

    def update(self, other: Any = None, **kwargs: str) -> None:  # type: ignore[override]
        if other is not None:
            pairs = other.items() if hasattr(other, "items") else other
            for k, v in pairs:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def clear(self) -> None:
        self._redis.delete(self._hash_key)

    def copy(self) -> dict[str, str]:  # type: ignore[override]
        """Return a plain dict snapshot.  The result is NOT a RedisDict."""
        return self._redis.hgetall(self._hash_key)

    # ------------------------------------------------------------------
    # Extras
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, str]:
        """Return a plain dict snapshot of all current key-value pairs."""
        return self._redis.hgetall(self._hash_key)

    @property
    def hash_key(self) -> str:
        """The Redis hash key that backs this dict."""
        return self._hash_key
