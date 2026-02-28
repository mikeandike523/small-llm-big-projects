"""
Tests for RedisDict: a dict subclass backed by a Redis hash.

Requires a running Redis instance.  Connection is configured via the
standard REDIS_HOST / REDIS_PORT environment variables (defaulting to
localhost:6379).

All tests use isolated hash keys with the prefix "test:redis_dict:"
and clean up after themselves so they can safely run against a shared
Redis instance.
"""
from __future__ import annotations

import os
import sys

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures: list[str] = []


def check(condition: bool, test_name: str, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {test_name}")
    else:
        msg = f"  {FAIL}  {test_name}"
        if detail:
            msg += f"\n       detail: {detail}"
        print(msg)
        _failures.append(test_name)


def get_failures() -> list[str]:
    return _failures


# ---------------------------------------------------------------------------
# Redis connection
# ---------------------------------------------------------------------------

def _get_redis():
    import redis
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        decode_responses=True,
    )


def _make_dict(suffix: str):
    """Return a fresh RedisDict backed by a test-specific hash key."""
    from src.utils.redis_dict import RedisDict
    r = _get_redis()
    hk = f"test:redis_dict:{suffix}"
    r.delete(hk)  # clean slate
    return RedisDict(r, hk), r, hk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_set_and_get():
    d, r, hk = _make_dict("set_get")
    try:
        d["alpha"] = "one"
        d["beta"] = "two"
        check(d["alpha"] == "one", "set+get: alpha == 'one'", repr(d["alpha"]))
        check(d["beta"] == "two", "set+get: beta == 'two'", repr(d["beta"]))
        # Value is actually in Redis, not just in the Python object
        check(r.hget(hk, "alpha") == "one", "set+get: alpha in Redis", r.hget(hk, "alpha"))
    finally:
        r.delete(hk)


def test_getitem_missing_raises():
    d, r, hk = _make_dict("missing_key")
    try:
        raised = False
        try:
            _ = d["no_such_key"]
        except KeyError:
            raised = True
        check(raised, "getitem: missing key raises KeyError")
    finally:
        r.delete(hk)


def test_contains():
    d, r, hk = _make_dict("contains")
    try:
        d["x"] = "y"
        check("x" in d, "contains: present key returns True")
        check("z" not in d, "contains: absent key returns False")
    finally:
        r.delete(hk)


def test_delete():
    d, r, hk = _make_dict("delete")
    try:
        d["k"] = "v"
        del d["k"]
        check("k" not in d, "delete: key gone after del")
        check(r.hexists(hk, "k") == 0, "delete: key gone from Redis too")
    finally:
        r.delete(hk)


def test_delete_missing_raises():
    d, r, hk = _make_dict("delete_missing")
    try:
        raised = False
        try:
            del d["no_such_key"]
        except KeyError:
            raised = True
        check(raised, "delete: missing key raises KeyError")
    finally:
        r.delete(hk)


def test_len():
    d, r, hk = _make_dict("len")
    try:
        check(len(d) == 0, "len: empty dict is 0")
        d["a"] = "1"
        d["b"] = "2"
        check(len(d) == 2, "len: two keys gives 2", str(len(d)))
        del d["a"]
        check(len(d) == 1, "len: after delete gives 1", str(len(d)))
    finally:
        r.delete(hk)


def test_iteration():
    d, r, hk = _make_dict("iteration")
    try:
        d["p"] = "1"
        d["q"] = "2"
        d["s"] = "3"
        keys_seen = set(d)
        check(keys_seen == {"p", "q", "s"}, "iter: all keys seen", str(keys_seen))
    finally:
        r.delete(hk)


def test_keys_values_items():
    d, r, hk = _make_dict("kvi")
    try:
        d["m"] = "M"
        d["n"] = "N"
        check(set(d.keys()) == {"m", "n"}, "keys(): correct set", str(d.keys()))
        check(set(d.values()) == {"M", "N"}, "values(): correct set", str(d.values()))
        check(set(d.items()) == {("m", "M"), ("n", "N")}, "items(): correct set", str(d.items()))
    finally:
        r.delete(hk)


def test_get_with_default():
    d, r, hk = _make_dict("get_default")
    try:
        d["exists"] = "yes"
        check(d.get("exists") == "yes", "get: present key returns value")
        check(d.get("missing") is None, "get: absent key returns None")
        check(d.get("missing", "fallback") == "fallback", "get: absent key returns default")
    finally:
        r.delete(hk)


def test_setdefault():
    d, r, hk = _make_dict("setdefault")
    try:
        # Key absent: sets and returns default
        result = d.setdefault("new_key", "default_val")
        check(result == "default_val", "setdefault: absent key returns default", repr(result))
        check(d["new_key"] == "default_val", "setdefault: absent key stored in Redis")

        # Key present: does NOT overwrite, returns existing value
        result2 = d.setdefault("new_key", "other_val")
        check(result2 == "default_val", "setdefault: present key not overwritten", repr(result2))
        check(d["new_key"] == "default_val", "setdefault: present key value unchanged")
    finally:
        r.delete(hk)


def test_update_from_dict():
    d, r, hk = _make_dict("update_dict")
    try:
        d.update({"u": "1", "v": "2"})
        check(d["u"] == "1", "update(dict): key u", repr(d.get("u")))
        check(d["v"] == "2", "update(dict): key v", repr(d.get("v")))

        # Overwrites existing
        d["u"] = "old"
        d.update({"u": "new"})
        check(d["u"] == "new", "update(dict): overwrites existing key")
    finally:
        r.delete(hk)


def test_update_from_kwargs():
    d, r, hk = _make_dict("update_kwargs")
    try:
        d.update(foo="bar", baz="qux")
        check(d["foo"] == "bar", "update(**kwargs): key foo")
        check(d["baz"] == "qux", "update(**kwargs): key baz")
    finally:
        r.delete(hk)


def test_pop():
    d, r, hk = _make_dict("pop")
    try:
        d["pop_me"] = "val"
        result = d.pop("pop_me")
        check(result == "val", "pop: returns value", repr(result))
        check("pop_me" not in d, "pop: key removed")

        # Missing with default
        result2 = d.pop("no_key", "sentinel")
        check(result2 == "sentinel", "pop: missing key returns default")

        # Missing without default raises
        raised = False
        try:
            d.pop("no_key")
        except KeyError:
            raised = True
        check(raised, "pop: missing key without default raises KeyError")
    finally:
        r.delete(hk)


def test_clear():
    d, r, hk = _make_dict("clear")
    try:
        d["a"] = "1"
        d["b"] = "2"
        d.clear()
        check(len(d) == 0, "clear: len is 0 after clear")
        check(r.exists(hk) == 0, "clear: Redis hash key deleted")
    finally:
        r.delete(hk)


def test_copy_returns_plain_dict():
    d, r, hk = _make_dict("copy")
    try:
        d["x"] = "X"
        d["y"] = "Y"
        snapshot = d.copy()
        check(type(snapshot) is dict, "copy: returns plain dict", type(snapshot).__name__)
        check(snapshot == {"x": "X", "y": "Y"}, "copy: snapshot has correct data", str(snapshot))
    finally:
        r.delete(hk)


def test_to_dict():
    d, r, hk = _make_dict("to_dict")
    try:
        d["one"] = "1"
        d["two"] = "2"
        result = d.to_dict()
        check(type(result) is dict, "to_dict: returns plain dict")
        check(result == {"one": "1", "two": "2"}, "to_dict: correct data", str(result))
    finally:
        r.delete(hk)


def test_isinstance_dict():
    d, r, hk = _make_dict("isinstance")
    try:
        check(isinstance(d, dict), "isinstance: RedisDict passes isinstance(x, dict)")
    finally:
        r.delete(hk)


def test_ensure_session_memory_compat():
    """
    Simulate _ensure_session_memory(session_data) as written in tool files.
    When session_data['memory'] is already a RedisDict it must NOT be replaced
    with a plain {}.
    """
    from src.utils.redis_dict import RedisDict
    r = _get_redis()
    hk = "test:redis_dict:ensure_compat"
    r.delete(hk)
    try:
        rd = RedisDict(r, hk)
        rd["pre"] = "existing"
        session_data = {"memory": rd}

        # Replicate the check done by every _ensure_session_memory in tool files
        memory = session_data.get("memory")
        if not isinstance(memory, dict):
            memory = {}
            session_data["memory"] = memory

        check(
            session_data["memory"] is rd,
            "ensure_session_memory compat: RedisDict not replaced by {}",
        )
        check(
            session_data["memory"].get("pre") == "existing",
            "ensure_session_memory compat: pre-existing value still accessible",
        )
    finally:
        r.delete(hk)


def test_data_visible_across_instances():
    """
    A second RedisDict pointing at the same hash key sees writes from the first.
    This is the fundamental cross-thread visibility guarantee.
    """
    from src.utils.redis_dict import RedisDict
    r = _get_redis()
    hk = "test:redis_dict:cross_instance"
    r.delete(hk)
    try:
        writer = RedisDict(r, hk)
        reader = RedisDict(r, hk)

        writer["shared"] = "hello"
        check(reader["shared"] == "hello", "cross-instance: reader sees writer's value")
        check("shared" in reader, "cross-instance: reader sees key via __contains__")
        check(len(reader) == 1, "cross-instance: reader sees correct len")
    finally:
        r.delete(hk)


def test_isolation_between_hash_keys():
    """Different hash keys do not share data."""
    from src.utils.redis_dict import RedisDict
    r = _get_redis()
    hk_a = "test:redis_dict:isolation_a"
    hk_b = "test:redis_dict:isolation_b"
    r.delete(hk_a)
    r.delete(hk_b)
    try:
        da = RedisDict(r, hk_a)
        db = RedisDict(r, hk_b)
        da["only_in_a"] = "yes"
        check("only_in_a" not in db, "isolation: key in A not visible in B")
        check(len(db) == 0, "isolation: B is still empty")
    finally:
        r.delete(hk_a)
        r.delete(hk_b)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run() -> list[str]:
    print("=== test_basic.py (RedisDict) ===")

    # Check Redis is reachable before running anything
    try:
        r = _get_redis()
        r.ping()
    except Exception as exc:
        print(f"  SKIP  Redis not reachable ({exc}); all tests skipped.")
        return []

    test_set_and_get()
    test_getitem_missing_raises()
    test_contains()
    test_delete()
    test_delete_missing_raises()
    test_len()
    test_iteration()
    test_keys_values_items()
    test_get_with_default()
    test_setdefault()
    test_update_from_dict()
    test_update_from_kwargs()
    test_pop()
    test_clear()
    test_copy_returns_plain_dict()
    test_to_dict()
    test_isinstance_dict()
    test_ensure_session_memory_compat()
    test_data_visible_across_instances()
    test_isolation_between_hash_keys()

    return _failures


if __name__ == "__main__":
    failures = run()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
