"""Session memory is copied to session_meta.memory_json only when it changed."""

from __future__ import annotations

import pytest

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import session_store
from src.utils.redis_dict import RedisDict
from src.utils.session_model import Session


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def expire(self, key, ttl):
        pass

    def delete(self, key):
        self.hashes.pop(key, None)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hsetnx(self, key, field, value):
        if field in self.hashes.get(key, {}):
            return 0
        self.hset(key, field, value)
        return 1

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hdel(self, key, field):
        return int(self.hashes.get(key, {}).pop(field, None) is not None)

    def hkeys(self, key):
        return list(self.hashes.get(key, {}))

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


@pytest.fixture
def saved(monkeypatch):
    """Run saves against a fake Redis; collect the `memory` passed to MySQL."""
    r = _FakeRedis()
    memories: list = []
    monkeypatch.setattr(session_store._state, "_get_redis", lambda: r)
    monkeypatch.setattr(
        session_store,
        "persist_save",
        lambda sid, events, turns, subturns, meta: memories.append(meta["memory"]),
    )
    session_store._state.take_session_memory_dirty("s1")
    memory = RedisDict(
        r,
        "session:s1:memory",
        on_change=lambda key, kind: session_store._state.mark_session_memory_dirty(
            "s1"
        ),
    )
    return r, memory, memories


def _save() -> None:
    session_store._save_session("s1", Session(session_id="s1"))


def test_unchanged_memory_is_not_rewritten(saved) -> None:
    _, _, memories = saved
    _save()
    _save()
    assert memories == [None, None]


def test_each_change_is_copied_once(saved) -> None:
    _, memory, memories = saved
    memory["notes"] = "a"
    _save()
    _save()
    memory["more"] = "b"
    del memory["notes"]
    _save()
    assert memories == [{"notes": "a"}, None, {"more": "b"}]


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.pop("k"),
        lambda m: m.clear(),
        lambda m: m.setdefault("new", "v"),
        lambda m: m.update({"k": "v2"}),
    ],
)
def test_every_redis_dict_mutation_marks_memory_changed(saved, change) -> None:
    r, memory, memories = saved
    r.hset("session:s1:memory", "k", "v")
    change(memory)
    _save()
    assert memories[-1] == r.hgetall("session:s1:memory")


def test_failed_save_keeps_the_change_pending(saved, monkeypatch) -> None:
    _, memory, memories = saved
    memory["notes"] = "a"

    def db_down(*args):
        raise RuntimeError("db down")

    monkeypatch.setattr(session_store, "persist_save", db_down)
    with pytest.raises(RuntimeError):
        _save()
    monkeypatch.setattr(
        session_store,
        "persist_save",
        lambda sid, events, turns, subturns, meta: memories.append(meta["memory"]),
    )
    _save()
    assert memories == [{"notes": "a"}]
