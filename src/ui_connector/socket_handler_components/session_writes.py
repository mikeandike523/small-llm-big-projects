"""Writing session changes to MySQL as they happen.

Each function here is called at the one place its change is made, and appends
exactly the events for that change (see _session_event_emit.py for the
builders). Every write is one MySQL transaction: the events, the
chat_turn_index / chat_history_cache rows they change, and the session_meta
row (persist_save). Failures propagate: a write that silently did not happen
is a hard error.

Nothing is diffed and nothing about what was saved lives in Redis. The only
bookkeeping is in memory on the objects being written (`saved_exchanges`,
`saved_todo_hash`), and it only moves after a commit, so a failed write is
repeated by the next one.

Writes run under runtime_settings.persistence_lock, like settings changes.
`advance_stream_watermark` is passed only at the agent's step boundaries (a
turn's start, each whole exchange, its end): there every socket event logged
so far describes state this write makes durable, so the Redis catch-up log's
bookmark moves past them (see event_log.py). Other writes (title, skills,
startup) can run mid-step and leave the bookmark alone.
"""

from __future__ import annotations

from typing import Callable

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components._session_event_emit import (
    Event,
    cache_rows_for_save,
    persist_window,
    session_created_events,
    skills_events,
    startup_done_events,
    summary_events,
    title_events,
    todo_events,
    turn_completed_events,
    turn_start_events,
    unsaved_exchange_events,
)
from src.utils.event_log import advance_watermark, latest_stream_id
from src.utils.session_events import (
    EVT_EXCHANGE_RECORDED,
    EVT_TODO_LIST_SET,
    derive_meta,
    todo_list_hash,
)
from src.utils.session_model import Session, Subturn, Turn
from src.utils.sql.chat_history_cache_db import persist_save


def _meta_fields(session_id: str, session: Session) -> dict:
    meta = derive_meta(session)
    return {
        "created_at": session.created_at,
        "schema_version": session.schema_version,
        "profile_name": session.profile_name,
        "initial_cwd": session.initial_cwd or "",
        "current_cwd": _state._session_current_cwd.get(session_id),
        "total_cost_usd": float(_state._session_costs.get(session_id) or 0.0),
        "last_context_usage": _state._session_last_context_usage.get(session_id),
        "turn_count": meta["turn_count"],
        "recent_task_titles": meta["recent_task_titles"],
        "task_title_count": meta["task_title_count"],
        "interim_response_as_thinking": session.interim_response_as_thinking,
        "load_custom_skills_tools": session.load_custom_skills_tools,
        "heartbeat_enabled": bool(
            (session.session_data.get("heartbeat_settings") or {}).get("enabled")
        ),
    }


def _mark_saved(session: Session, events: list[Event]) -> None:
    """Move the in-memory "already written" counters past `events`."""
    subturns = {
        st.id: st for _, turn in persist_window(session) for st in turn.subturns
    }
    for event_type, payload in events:
        if event_type == EVT_EXCHANGE_RECORDED:
            st = subturns.get(payload["subturn_id"])
            if st is not None:
                st.saved_exchanges = max(st.saved_exchanges, payload["index"] + 1)
        elif event_type == EVT_TODO_LIST_SET:
            session.saved_todo_hash = todo_list_hash(payload["items"])


def _commit(
    session_id: str,
    session: Session,
    build_events: Callable[[], list[Event]],
    *,
    advance_stream_watermark: bool = False,
) -> None:
    """Build the events under the persistence lock, then write them."""
    if not session.turns_loaded:
        raise RuntimeError(
            f"Session {session_id} was loaded without its turns and cannot be saved."
        )
    with runtime_settings.persistence_lock(session_id):
        # The Session copy picks up settings changed elsewhere (they were
        # written as their own events by setting_events.py).
        runtime_settings.merge_into_session(session_id, session)
        r = _state._get_redis() if advance_stream_watermark else None
        # Read before building: every event logged up to here is covered.
        stream_mark = (latest_stream_id(r, session_id) or "0-0") if r else None
        events = build_events()
        if events:
            turn_rows, subturn_rows = (
                cache_rows_for_save(session, events)
                if session.history_cache_compatible
                else ([], [])
            )
            persist_save(
                session_id,
                events,
                turn_rows,
                subturn_rows,
                _meta_fields(session_id, session),
            )
            _mark_saved(session, events)
        if stream_mark is not None:
            advance_watermark(r, session_id, stream_mark, _state._SESSION_TTL)


def write_session_created(session_id: str, session: Session) -> None:
    _commit(session_id, session, lambda: session_created_events(session))


def write_startup_done(session_id: str, session: Session) -> None:
    """Startup tool calls ran (they may also have changed the todo list)."""
    _commit(session_id, session, lambda: startup_done_events() + todo_events(session))


def write_turn_start(
    session_id: str, session: Session, turn: Turn, subturn: Subturn, *, reopened: bool
) -> None:
    """A new turn or follow-up subturn (plus the todo list it may have reset)."""
    _commit(
        session_id,
        session,
        lambda: turn_start_events(turn, subturn, reopened=reopened)
        + todo_events(session),
        advance_stream_watermark=True,
    )


def write_title(session_id: str, session: Session, turn: Turn) -> None:
    _commit(session_id, session, lambda: title_events(turn))


def write_skills(session_id: str, session: Session, turn: Turn) -> None:
    _commit(session_id, session, lambda: skills_events(turn))


def write_step(session_id: str, session: Session, subturn: Subturn) -> None:
    """An agent step: the exchange(s) just appended, and the todo list."""
    _commit(
        session_id,
        session,
        lambda: unsaved_exchange_events(subturn) + todo_events(session),
        advance_stream_watermark=True,
    )


def write_turn_end(
    session_id: str, session: Session, turn: Turn, subturn: Subturn
) -> None:
    """The turn's last exchange(s), the subturn summary and its completion."""
    _commit(
        session_id,
        session,
        lambda: unsaved_exchange_events(subturn)
        + summary_events(subturn)
        + turn_completed_events(turn)
        + todo_events(session),
        advance_stream_watermark=True,
    )
