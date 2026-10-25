"""MySQL failures on session load/write propagate (no silent fallbacks)."""

from __future__ import annotations

import mysql.connector
import pytest

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import (
    session_db_load,
    session_writes,
)
from src.utils.request_error_formatting import (
    classify_llm_request_error,
    failure_message,
)
from src.utils.session_model import LLMExchange, Session, Subturn, Turn


def _db_down(*args, **kwargs):
    raise mysql.connector.errors.OperationalError("db down")


def test_failed_write_raises_and_leaves_the_bookmark(monkeypatch) -> None:
    marks: list = []
    monkeypatch.setattr(session_writes._state, "_get_redis", lambda: object())
    monkeypatch.setattr(session_writes, "persist_save", _db_down)
    monkeypatch.setattr(session_writes, "latest_stream_id", lambda r, sid: "9-0")
    monkeypatch.setattr(
        session_writes, "advance_watermark", lambda *args: marks.append(args)
    )
    session = Session(session_id="s1")
    st = Subturn(id="st1", user_text="q", user_text_with_context="q")
    session.current_turn = Turn(id="t1", subturns=[st])
    st.exchanges.append(LLMExchange(assistant_content="a"))

    with pytest.raises(mysql.connector.Error):
        session_writes.write_step("s1", session, st)
    assert marks == []
    # Not marked written, so the next write repeats the exchange.
    assert st.saved_exchanges == 0


def test_failed_load_raises_instead_of_returning_a_blank_session(
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_db_load, "load_session_meta", _db_down)
    with pytest.raises(mysql.connector.Error):
        session_db_load.load_session_from_db("s1")


def test_failed_event_read_does_not_mark_the_session_corrupt(monkeypatch) -> None:
    corrupt: list = []
    monkeypatch.setattr(
        session_db_load, "load_session_meta", lambda sid: {"schema_version": 6}
    )
    monkeypatch.setattr(session_db_load, "_warn_uncached", lambda sid: None)
    monkeypatch.setattr(session_db_load, "load_session_events", _db_down)
    monkeypatch.setattr(session_db_load, "mark_session_corrupt", corrupt.append)
    with pytest.raises(mysql.connector.Error):
        session_db_load.load_session_from_db("s1")
    assert corrupt == []


def test_database_errors_get_a_database_message() -> None:
    exc = mysql.connector.errors.OperationalError("db down")
    classified = classify_llm_request_error(exc)
    assert classified["gui_message"].startswith("Database error")
    assert classified["history_marker"] == "[Stopped - Database Error]"
    assert failure_message(exc).startswith("Database error")
    assert "LLM" not in failure_message(RuntimeError("boom"))
