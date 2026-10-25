"""The events each session write appends, built from the in-memory Session.

Every place that changes a session's durable state writes its own events
directly (see session_writes.py): a new turn writes `turn_started` +
`subturn_started`, an agent step writes the `exchange_recorded` it just
appended, and so on. The builders here are pure: they turn the model objects
into `(event_type, payload)` pairs and decide nothing about when to write.

Two in-memory counters (never stored) say what is already written, so a write
that failed is picked up by the next one: `Subturn.saved_exchanges` and
`Session.saved_todo_hash`. Replay sets both, because everything replayed is in
MySQL by definition.

Only the last two turns (:func:`persist_window`) can still change: older turns
are sealed.
"""

from __future__ import annotations

from src.utils.session_events import (
    EVT_EXCHANGE_RECORDED,
    EVT_HEARTBEAT_SETTINGS_SET,
    EVT_SESSION_CREATED,
    EVT_SKILLS_SELECTED,
    EVT_STARTUP_DONE_SET,
    EVT_SUBTURN_STARTED,
    EVT_SUBTURN_SUMMARY_SET,
    EVT_TITLE_SET,
    EVT_TODO_LIST_SET,
    EVT_TURN_COMPLETED,
    EVT_TURN_REOPENED,
    EVT_TURN_STARTED,
    exchange_payload,
    heartbeat_settings_payload,
    session_created_payload,
    subturn_started_payload,
    todo_list_hash,
    turn_completed_payload,
)
from src.utils.session_cache_projection import project_subturn_row, project_turn_row
from src.utils.session_model import Session, Subturn, Turn

Event = tuple[str, dict]


def session_created_events(session: Session) -> list[Event]:
    events: list[Event] = [(EVT_SESSION_CREATED, session_created_payload(session))]
    heartbeat_settings = session.session_data.get("heartbeat_settings")
    if heartbeat_settings is not None:
        events.append(
            (EVT_HEARTBEAT_SETTINGS_SET, heartbeat_settings_payload(heartbeat_settings))
        )
    return events


def startup_done_events() -> list[Event]:
    return [(EVT_STARTUP_DONE_SET, {})]


def turn_start_events(turn: Turn, subturn: Subturn, *, reopened: bool) -> list[Event]:
    """A new turn, or a follow-up subturn reopening the last completed turn."""
    return [
        (EVT_TURN_REOPENED if reopened else EVT_TURN_STARTED, {"turn_id": turn.id}),
        (EVT_SUBTURN_STARTED, subturn_started_payload(turn.id, subturn)),
    ]


def title_events(turn: Turn) -> list[Event]:
    if not turn.task_title:
        return []
    return [(EVT_TITLE_SET, {"turn_id": turn.id, "title": turn.task_title})]


def skills_events(turn: Turn) -> list[Event]:
    if not turn.selected_skill_ids:
        return []
    return [
        (
            EVT_SKILLS_SELECTED,
            {"turn_id": turn.id, "skill_ids": list(turn.selected_skill_ids)},
        )
    ]


def exchange_event(subturn: Subturn, index: int) -> Event:
    return (
        EVT_EXCHANGE_RECORDED,
        {
            "subturn_id": subturn.id,
            "index": index,
            "exchange": exchange_payload(subturn.exchanges[index]),
        },
    )


def unsaved_exchange_events(subturn: Subturn) -> list[Event]:
    """Exchanges appended since the last successful write of this subturn."""
    return [
        exchange_event(subturn, i)
        for i in range(subturn.saved_exchanges, len(subturn.exchanges))
    ]


def summary_events(subturn: Subturn) -> list[Event]:
    if subturn.detailed_summary is None:
        return []
    return [
        (
            EVT_SUBTURN_SUMMARY_SET,
            {"subturn_id": subturn.id, "detailed_summary": subturn.detailed_summary},
        )
    ]


def turn_completed_events(turn: Turn) -> list[Event]:
    return [(EVT_TURN_COMPLETED, turn_completed_payload(turn))]


def todo_events(session: Session) -> list[Event]:
    """The session-global todo list, if it changed since it was last written."""
    items = session.session_data.get("todo_list") or []
    saved = session.saved_todo_hash or todo_list_hash([])
    if todo_list_hash(items) == saved:
        return []
    return [(EVT_TODO_LIST_SET, {"items": items})]


def persist_window(session: Session) -> list[tuple[int, Turn]]:
    """The turns a write can still change, as `(turn_seq, turn)`: the last two.

    Only the most recent completed turn can be reopened by a follow-up, and a
    new turn is always appended, so every older turn is sealed: its events are
    in MySQL and it never changes again.
    """
    all_turns = list(session.completed_turns)
    if session.current_turn is not None:
        all_turns.append(session.current_turn)
    first_seq = max(0, len(all_turns) - 2)
    return [(first_seq + i + 1, t) for i, t in enumerate(all_turns[first_seq:])]


def cache_rows_for_save(
    session: Session, events: list[Event]
) -> tuple[list[dict], list[dict]]:
    """chat_turn_index / chat_history_cache rows changed by `events`.

    Only turns in the persist window can have events, and only the turns and
    subturns those events name are re-projected. Raises if an event names a
    turn loaded from the cache (a stub must never be written back).
    """
    turn_ids: set[str] = set()
    subturn_ids: set[str] = set()
    for _, payload in events:
        if payload.get("turn_id"):
            turn_ids.add(payload["turn_id"])
        if payload.get("subturn_id"):
            subturn_ids.add(payload["subturn_id"])
    turn_rows: list[dict] = []
    subturn_rows: list[dict] = []
    for turn_seq, turn in persist_window(session):
        named = turn.id in turn_ids or any(st.id in subturn_ids for st in turn.subturns)
        if named and turn.from_cache:
            raise RuntimeError(
                f"Turn {turn.id} was loaded from the chat history cache and "
                "cannot be persisted."
            )
        if turn.id in turn_ids:
            turn_rows.append(project_turn_row(turn, turn_seq, None))
        subturn_rows.extend(
            project_subturn_row(turn_seq, i, st)
            for i, st in enumerate(turn.subturns, 1)
            if st.id in subturn_ids
        )
    return turn_rows, subturn_rows
