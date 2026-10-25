"""Test harness: the real session write path over an in-memory event log.

`install(monkeypatch)` points session_writes (and setting_events) at an
`EventLog` that stores what MySQL would: the session_events rows plus the
chat_turn_index / chat_history_cache rows, using the same upsert rules as
chat_history_cache_db. The helpers below then make the same model changes and
write calls as the server (socket_events_turn.py and agent_loop.py), so tests
exercise the code that runs in production.
"""

from __future__ import annotations

import json

from src.ui_connector.socket_handler_components import (
    runtime_settings,
    session_writes,
    setting_events,
)
from src.utils.session_model import LLMExchange, Session, Subturn, Turn


class EventLog:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.index: dict[int, dict] = {}
        self.cache: dict[tuple[int, int], dict] = {}
        self.meta: dict | None = None
        self.commits: list[list[str]] = []
        self.setting_meta: list[dict] = []
        self.watermarks: list[str] = []

    def _append(self, events) -> dict[str, int]:
        starts: dict[str, int] = {}
        for event_type, payload in events:
            row_id = len(self.rows) + 1
            self.rows.append(
                {
                    "id": row_id,
                    "event_type": event_type,
                    "payload": json.loads(json.dumps(payload)),
                }
            )
            if event_type == "turn_started":
                starts[payload["turn_id"]] = row_id
        return starts

    def persist_save(self, session_id, events, turn_rows, subturn_rows, meta) -> None:
        starts = self._append(events)
        self.meta = meta
        for row in turn_rows:
            # Same rule as chat_history_cache_db._execute_upsert_turn_rows.
            start = starts.get(row["turn_id"])
            if start is not None:
                self.index[row["turn_seq"]] = {**row, "start_event_id": start}
            else:
                existing = self.index[row["turn_seq"]]
                assert existing["turn_id"] == row["turn_id"]
                existing.update(title=row["title"], completed=row["completed"])
        for row in subturn_rows:
            self.cache[(row["turn_seq"], row["subturn_seq"])] = row
        self.commits.append([event_type for event_type, _ in events])

    def append_setting_event(self, session_id, event_type, payload, meta) -> None:
        self._append([(event_type, payload)])
        self.setting_meta.append(meta)
        self.commits.append([event_type])

    def starts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for row in self.rows:
            if row["event_type"] == "turn_started":
                found.setdefault(row["payload"]["turn_id"], row["id"])
        return found

    def types(self) -> list[str]:
        return [row["event_type"] for row in self.rows]


def install(monkeypatch, session_id: str = "s1") -> EventLog:
    log = EventLog()
    runtime_settings.discard(session_id)
    monkeypatch.setattr(session_writes, "persist_save", log.persist_save)
    monkeypatch.setattr(
        setting_events, "append_setting_event", log.append_setting_event
    )
    monkeypatch.setattr(session_writes, "latest_stream_id", lambda r, sid: None)
    monkeypatch.setattr(
        session_writes,
        "advance_watermark",
        lambda r, sid, mark, ttl: log.watermarks.append(mark),
    )
    monkeypatch.setattr(session_writes._state, "_get_redis", lambda: object())
    return log


# ---------------------------------------------------------------------------
# The server's model changes + write calls
# ---------------------------------------------------------------------------


def subturn(sid: str, text: str, **kwargs) -> Subturn:
    return Subturn(
        id=sid, user_text=text, user_text_with_context=f"[ctx] {text}", **kwargs
    )


def create(session: Session) -> None:
    session_writes.write_session_created(session.session_id, session)


def start_turn(
    session: Session, turn_id: str, st: Subturn, *, follow_up: bool = False
) -> Turn:
    """socket_events_turn: a new turn, or a follow-up reopening the last one."""
    if follow_up:
        turn = session.completed_turns.pop()
        turn.completed = False
        st.is_continuation = True
        turn.subturns.append(st)
    else:
        turn = Turn(id=turn_id, subturns=[st])
        session.session_data["todo_list"] = []
    session.current_turn = turn
    session_writes.write_turn_start(
        session.session_id, session, turn, st, reopened=follow_up
    )
    return turn


def set_title(session: Session, turn: Turn, title: str) -> None:
    turn.task_title = title
    session_writes.write_title(session.session_id, session, turn)


def step(session: Session, st: Subturn, exchange: LLMExchange) -> None:
    """agent_loop: one exchange appended, then written."""
    st.exchanges.append(exchange)
    session_writes.write_step(session.session_id, session, st)


def end_turn(
    session: Session,
    turn: Turn,
    st: Subturn,
    final: LLMExchange | None,
    *,
    cancelled: bool = False,
) -> None:
    """agent_loop's finally: the last exchange, completion, then one write."""
    if final is not None:
        st.exchanges.append(final)
    turn.was_cancelled = cancelled
    turn.completed = True
    session.completed_turns.append(turn)
    session.current_turn = None
    session_writes.write_turn_end(session.session_id, session, turn, st)
