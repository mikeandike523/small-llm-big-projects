"""Event-sourced session reconstruction (migration v11).

A session is persisted as an append-only list of semantic events in the
`session_events` table. To reconstruct a `Session` we select its events in `id`
order and fold them with :func:`replay_events`.

This module owns three concerns:
  * the event-type vocabulary (the ``EVT_*`` constants),
  * the *reducer* that folds events into a `Session` (:class:`ReplayState`,
    :func:`apply_event`, :func:`replay_events`),
  * the small payload/hash builders used by the diff-on-save emitter
    (`_session_event_emit.py`) so payload shapes live next to the reducer that
    reads them.

Persisted exchange payloads deliberately omit ``reasoning`` (`<think>` / IRAT
thinking): it is large, already excluded from LLM context, and not wanted for
fine-tuning. After a cold reload, completed-turn reasoning panels are empty.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from src.utils.session_model import (
    CURRENT_SCHEMA_VERSION,
    LLMExchange,
    Session,
    Subturn,
    Turn,
    llm_exchange_from_dict,
    llm_exchange_to_dict,
)

# ---------------------------------------------------------------------------
# Event vocabulary
# ---------------------------------------------------------------------------

EVT_SESSION_CREATED = "session_created"
EVT_TURN_STARTED = "turn_started"
EVT_TITLE_SET = "title_set"
EVT_SKILLS_SELECTED = "skills_selected"
EVT_SUBTURN_STARTED = "subturn_started"
EVT_EXCHANGE_RECORDED = "exchange_recorded"
EVT_SUBTURN_SUMMARY_SET = "subturn_summary_set"
EVT_TURN_COMPLETED = "turn_completed"
# Session-global live todo list (session_data["todo_list"]); last-writer-wins.
EVT_TODO_LIST_SET = "todo_list_set"


# ---------------------------------------------------------------------------
# Payload / hash builders (shared with the diff-on-save emitter)
# ---------------------------------------------------------------------------


def exchange_payload(ex: LLMExchange) -> dict:
    """Serialize an exchange for persistence, dropping `reasoning`."""
    d = llm_exchange_to_dict(ex)
    d.pop("reasoning", None)
    return d


def exchange_hash(ex: LLMExchange) -> str:
    """Stable hash of an exchange's persisted form (drives the save cursor)."""
    blob = json.dumps(exchange_payload(ex), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def todo_list_hash(items: list) -> str:
    """Stable hash of the live todo list (drives the save cursor)."""
    blob = json.dumps(items or [], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def session_created_payload(session: Session) -> dict:
    return {
        "initial_cwd": session.initial_cwd,
        "skills_path": session.skills_path,
        "custom_tools_path": session.custom_tools_path,
        "profile_name": session.profile_name,
        "interim_response_as_thinking": session.interim_response_as_thinking,
        "startup_tool_calls": session.startup_tool_calls,
        "startup_done": session.startup_done,
        "created_at": session.created_at,
        "schema_version": session.schema_version,
    }


def subturn_started_payload(turn_id: str, st: Subturn) -> dict:
    return {
        "turn_id": turn_id,
        "subturn_id": st.id,
        "user_text": st.user_text,
        "user_text_with_context": st.user_text_with_context,
        "is_continuation": st.is_continuation,
    }


def turn_completed_payload(turn: Turn) -> dict:
    return {
        "turn_id": turn.id,
        "condensed_user": turn.condensed_user,
        "condensed_assistant": turn.condensed_assistant,
        "completed": turn.completed,
        "was_cancelled": turn.was_cancelled,
        "todo_snapshot": turn.todo_snapshot,
        "was_impossible": turn.was_impossible,
        "impossible_reason": turn.impossible_reason,
    }


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


class ReplayState:
    """Mutable working state for folding events into a `Session`."""

    def __init__(self, session_id: str) -> None:
        self.session = Session(session_id=session_id)
        self._turns: dict[str, Turn] = {}
        self._turn_order: list[str] = []
        self._subturns: dict[str, Subturn] = {}

    def apply(self, event_type: str, payload: dict) -> None:
        handler = _HANDLERS.get(event_type)
        if handler is None:
            return  # forward-compat: ignore unknown event types
        handler(self, payload)

    def _ensure_turn(self, turn_id: str) -> Turn:
        turn = self._turns.get(turn_id)
        if turn is None:
            turn = Turn(id=turn_id, subturns=[])
            self._turns[turn_id] = turn
            self._turn_order.append(turn_id)
        return turn

    def to_session(self) -> Session:
        ordered = [self._turns[t] for t in self._turn_order]
        if ordered and not ordered[-1].completed:
            self.session.current_turn = ordered[-1]
            self.session.completed_turns = ordered[:-1]
        else:
            self.session.current_turn = None
            self.session.completed_turns = ordered
        return self.session


def _on_session_created(state: ReplayState, p: dict) -> None:
    s = state.session
    s.initial_cwd = p.get("initial_cwd", "")
    s.skills_path = p.get("skills_path")
    s.custom_tools_path = p.get("custom_tools_path")
    s.profile_name = p.get("profile_name")
    s.interim_response_as_thinking = p.get("interim_response_as_thinking", False)
    s.startup_tool_calls = p.get("startup_tool_calls", [])
    s.startup_done = p.get("startup_done", False)
    s.created_at = p.get("created_at", 0.0)
    s.schema_version = p.get("schema_version", CURRENT_SCHEMA_VERSION)


def _on_turn_started(state: ReplayState, p: dict) -> None:
    state._ensure_turn(p["turn_id"])


def _on_title_set(state: ReplayState, p: dict) -> None:
    state._ensure_turn(p["turn_id"]).task_title = p.get("title")


def _on_skills_selected(state: ReplayState, p: dict) -> None:
    state._ensure_turn(p["turn_id"]).selected_skill_ids = p.get("skill_ids", [])


def _on_subturn_started(state: ReplayState, p: dict) -> None:
    subturn_id = p["subturn_id"]
    if subturn_id in state._subturns:
        return
    turn = state._ensure_turn(p["turn_id"])
    st = Subturn(
        id=subturn_id,
        user_text=p.get("user_text", ""),
        user_text_with_context=p.get("user_text_with_context", ""),
        exchanges=[],
        is_continuation=p.get("is_continuation", False),
    )
    turn.subturns.append(st)
    state._subturns[subturn_id] = st


def _on_exchange_recorded(state: ReplayState, p: dict) -> None:
    st = state._subturns.get(p["subturn_id"])
    if st is None:
        return
    idx = p["index"]
    ex = llm_exchange_from_dict(p.get("exchange", {}))
    while len(st.exchanges) <= idx:
        st.exchanges.append(LLMExchange())
    st.exchanges[idx] = ex  # last-writer-wins


def _on_subturn_summary_set(state: ReplayState, p: dict) -> None:
    st = state._subturns.get(p["subturn_id"])
    if st is not None:
        st.detailed_summary = p.get("detailed_summary")


def _on_turn_completed(state: ReplayState, p: dict) -> None:
    turn = state._ensure_turn(p["turn_id"])
    turn.condensed_user = p.get("condensed_user", "")
    turn.condensed_assistant = p.get("condensed_assistant", "")
    turn.completed = p.get("completed", True)
    turn.was_cancelled = p.get("was_cancelled", False)
    turn.todo_snapshot = p.get("todo_snapshot", [])
    turn.was_impossible = p.get("was_impossible", False)
    turn.impossible_reason = p.get("impossible_reason")


def _on_todo_list_set(state: ReplayState, p: dict) -> None:
    # Session-global live working todo list; last event wins.
    state.session.session_data["todo_list"] = p.get("items", [])


_HANDLERS = {
    EVT_SESSION_CREATED: _on_session_created,
    EVT_TURN_STARTED: _on_turn_started,
    EVT_TITLE_SET: _on_title_set,
    EVT_SKILLS_SELECTED: _on_skills_selected,
    EVT_SUBTURN_STARTED: _on_subturn_started,
    EVT_EXCHANGE_RECORDED: _on_exchange_recorded,
    EVT_SUBTURN_SUMMARY_SET: _on_subturn_summary_set,
    EVT_TURN_COMPLETED: _on_turn_completed,
    EVT_TODO_LIST_SET: _on_todo_list_set,
}


def apply_event(state: ReplayState, event_type: str, payload: dict) -> None:
    """Fold a single event into the replay state (ignores unknown types)."""
    state.apply(event_type, payload)


def replay_events(session_id: str, rows: Iterable[dict]) -> Session:
    """Reconstruct a Session from its events (each row: {event_type, payload}).

    `payload` may arrive as a dict or a JSON string (driver-dependent); both are
    handled. Rows must already be ordered by `id` (the SQL query does this).
    """
    state = ReplayState(session_id)
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        state.apply(row.get("event_type", ""), payload)
    return state.to_session()


def derive_meta(session: Session) -> dict[str, Any]:
    """Lightweight list-view metadata derived from a reconstructed Session."""
    completed = session.completed_turns
    current = session.current_turn
    titles = [t.task_title for t in completed if t.task_title]
    if current and current.task_title:
        titles.append(current.task_title)
    return {
        "turn_count": len(completed) + (1 if current else 0),
        "task_titles": titles,
    }
