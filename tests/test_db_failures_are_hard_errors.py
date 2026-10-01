"""MySQL failures on session load/save propagate (no silent fallbacks)."""

from __future__ import annotations

import mysql.connector
import pytest

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import session_store
from src.utils.request_error_formatting import (
    classify_llm_request_error,
    failure_message,
)
from src.utils.session_model import Session


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def hgetall(self, key):
        return {}

    def expire(self, key, ttl):
        pass


def _db_down(*args, **kwargs):
    raise mysql.connector.errors.OperationalError("db down")


def test_failed_save_raises_and_leaves_the_bookmark(monkeypatch) -> None:
    r = _FakeRedis()
    marks: list = []
    monkeypatch.setattr(session_store._state, "_get_redis", lambda: r)
    monkeypatch.setattr(session_store, "append_events", _db_down)
    monkeypatch.setattr(session_store, "latest_stream_id", lambda r, sid: "9-0")
    monkeypatch.setattr(
        session_store, "set_watermark", lambda *args: marks.append(args)
    )

    with pytest.raises(mysql.connector.Error):
        session_store._save_session(
            "s1", Session(session_id="s1"), advance_stream_watermark=True
        )
    assert marks == []
    # The cursor was not saved, so the next save re-emits the unsaved events.
    assert "session:s1:persist_state" not in r.values


def test_failed_load_raises_instead_of_returning_a_blank_session(
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_store, "load_session_meta", _db_down)
    with pytest.raises(mysql.connector.Error):
        session_store._session_from_db("s1", cold=True)


def test_failed_event_read_does_not_mark_the_session_corrupt(monkeypatch) -> None:
    corrupt: list = []
    monkeypatch.setattr(
        session_store, "load_session_meta", lambda sid: {"schema_version": 6}
    )
    monkeypatch.setattr(session_store, "load_session_events", _db_down)
    monkeypatch.setattr(session_store, "mark_session_corrupt", corrupt.append)
    with pytest.raises(mysql.connector.Error):
        session_store._session_from_db("s1", cold=True)
    assert corrupt == []


def test_database_errors_get_a_database_message() -> None:
    exc = mysql.connector.errors.OperationalError("db down")
    classified = classify_llm_request_error(exc)
    assert classified["gui_message"].startswith("Database error")
    assert classified["history_marker"] == "[Stopped - Database Error]"
    assert failure_message(exc).startswith("Database error")
    assert "LLM" not in failure_message(RuntimeError("boom"))
