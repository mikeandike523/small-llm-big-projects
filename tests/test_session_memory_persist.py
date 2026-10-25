"""Session memory is read and written directly in MySQL (`session_memory`)."""

from __future__ import annotations

import pytest

from src.utils import session_memory
from src.utils.session_memory import SessionMemory


class _FakeMemoryTable:
    """session_memory_db over a dict of (session_id, key) -> value."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], str] = {}

    def install(self, monkeypatch) -> None:
        db = session_memory._db
        monkeypatch.setattr(
            db, "get_memory_value", lambda sid, k: self.rows.get((sid, k))
        )
        monkeypatch.setattr(db, "has_memory_key", lambda sid, k: (sid, k) in self.rows)
        monkeypatch.setattr(db, "list_memory_keys", self._keys)
        monkeypatch.setattr(db, "count_memory_keys", lambda sid: len(self._keys(sid)))
        monkeypatch.setattr(
            db,
            "load_memory",
            lambda sid: {k: self.rows[(sid, k)] for k in self._keys(sid)},
        )
        monkeypatch.setattr(db, "set_memory_value", self._set)
        monkeypatch.setattr(db, "add_memory_value", self._add)
        monkeypatch.setattr(
            db,
            "delete_memory_key",
            lambda sid, k: self.rows.pop((sid, k), None) is not None,
        )
        monkeypatch.setattr(db, "clear_memory", self._clear)

    def _keys(self, sid: str) -> list[str]:
        return sorted(k for s, k in self.rows if s == sid)

    def _set(self, sid: str, key: str, value: str) -> None:
        self.rows[(sid, key)] = value

    def _add(self, sid: str, key: str, value: str) -> bool:
        if (sid, key) in self.rows:
            return False
        self.rows[(sid, key)] = value
        return True

    def _clear(self, sid: str) -> None:
        for key in self._keys(sid):
            del self.rows[(sid, key)]


@pytest.fixture
def table(monkeypatch) -> _FakeMemoryTable:
    t = _FakeMemoryTable()
    t.install(monkeypatch)
    return t


def test_writes_go_straight_to_the_table(table) -> None:
    changes: list = []
    memory = SessionMemory("s1", on_change=lambda k, kind: changes.append((k, kind)))
    memory["b"] = "2"
    memory["a"] = "1"
    del memory["b"]

    assert table.rows == {("s1", "a"): "1"}
    assert changes == [("b", "modified"), ("a", "modified"), ("b", "deleted")]
    # Another view of the same session (e.g. another process) sees it at once.
    other = SessionMemory("s1")
    assert other.to_dict() == {"a": "1"} and "a" in other and len(other) == 1


def test_dict_behaviour(table) -> None:
    memory = SessionMemory("s1")
    memory.update({"x": "1"}, y="2")
    assert isinstance(memory, dict)
    assert memory.keys() == ["x", "y"] and list(memory) == ["x", "y"]
    assert memory.items() == [("x", "1"), ("y", "2")]
    assert memory.get("missing", "d") == "d"
    assert memory.setdefault("x", "other") == "1"
    assert memory.setdefault("z", "3") == "3"
    assert memory.pop("z") == "3" and memory.pop("z", None) is None
    with pytest.raises(KeyError):
        memory["z"]
    with pytest.raises(KeyError):
        del memory["z"]
    memory.clear()
    assert memory.to_dict() == {} and table.rows == {}


def test_sessions_are_separate(table) -> None:
    SessionMemory("s1")["k"] = "one"
    SessionMemory("s2")["k"] = "two"
    assert SessionMemory("s1")["k"] == "one"
    SessionMemory("s2").clear()
    assert SessionMemory("s1").to_dict() == {"k": "one"}
