"""Diff-on-save event emission for event-sourced sessions.

The agent loop mutates the in-memory `Session` and calls `_save_session`; rather
than instrument the loop, we diff the Session against a small *persist cursor*
and append only the new/changed events. This keeps all persistence logic in one
place.

The cursor lives in Redis (`session:{id}:persist_state`) and records what has
already been emitted: whether `session_created` fired, and per turn/subturn the
flags + per-exchange hashes needed to detect deltas. Turns/subturns/exchanges
are append-only in the model, and exchanges are mutated in place (tool results /
final content fill in after first append), so exchanges use a content hash with
last-writer-wins re-emission.

IMPORTANT: after a cold load (Redis fully evicted) the cursor is gone. Callers
must rebuild it from the replayed Session via :func:`build_cursor` before the
next save, or every event would be re-emitted as a duplicate.
"""

from __future__ import annotations

import json

import redis

from src.utils.session_events import (
    EVT_EXCHANGE_RECORDED,
    EVT_SESSION_CREATED,
    EVT_SKILLS_SELECTED,
    EVT_SUBTURN_STARTED,
    EVT_SUBTURN_SUMMARY_SET,
    EVT_TITLE_SET,
    EVT_TODO_LIST_SET,
    EVT_TURN_COMPLETED,
    EVT_TURN_STARTED,
    exchange_hash,
    exchange_payload,
    session_created_payload,
    subturn_started_payload,
    todo_list_hash,
    turn_completed_payload,
)
from src.utils.session_model import Session


def _persist_state_key(session_id: str) -> str:
    return f"session:{session_id}:persist_state"


def load_cursor(r: redis.Redis, session_id: str) -> dict:
    raw = r.get(_persist_state_key(session_id))
    if not raw:
        return {}
    try:
        cur = json.loads(raw)
        return cur if isinstance(cur, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_cursor(r: redis.Redis, session_id: str, cursor: dict, ttl: int) -> None:
    r.setex(_persist_state_key(session_id), ttl, json.dumps(cursor, ensure_ascii=False))


def compute_events(session: Session, cursor: dict) -> list[tuple[str, dict]]:
    """Return new events since `cursor`, mutating `cursor` to reflect them.

    Pass a fresh `{}` to emit the session from scratch; pass the stored cursor to
    emit only the delta.
    """
    events: list[tuple[str, dict]] = []

    if not cursor.get("created"):
        events.append((EVT_SESSION_CREATED, session_created_payload(session)))
        cursor["created"] = True

    turns_cursor: dict = cursor.setdefault("turns", {})

    all_turns = list(session.completed_turns)
    if session.current_turn is not None:
        all_turns.append(session.current_turn)

    for turn in all_turns:
        tc = turns_cursor.get(turn.id)
        if tc is None:
            events.append((EVT_TURN_STARTED, {"turn_id": turn.id}))
            tc = {"title_set": False, "skills": None, "completed": False, "subturns": {}}
            turns_cursor[turn.id] = tc

        if turn.task_title and not tc["title_set"]:
            events.append(
                (EVT_TITLE_SET, {"turn_id": turn.id, "title": turn.task_title})
            )
            tc["title_set"] = True

        if turn.selected_skill_ids and tc["skills"] != turn.selected_skill_ids:
            events.append(
                (
                    EVT_SKILLS_SELECTED,
                    {"turn_id": turn.id, "skill_ids": turn.selected_skill_ids},
                )
            )
            tc["skills"] = list(turn.selected_skill_ids)

        sub_cursor: dict = tc["subturns"]
        for st in turn.subturns:
            sc = sub_cursor.get(st.id)
            if sc is None:
                events.append(
                    (EVT_SUBTURN_STARTED, subturn_started_payload(turn.id, st))
                )
                sc = {"summary": None, "exchange_hashes": []}
                sub_cursor[st.id] = sc

            hashes: list = sc["exchange_hashes"]
            for idx, ex in enumerate(st.exchanges):
                h = exchange_hash(ex)
                if idx >= len(hashes):
                    events.append(
                        (
                            EVT_EXCHANGE_RECORDED,
                            {
                                "subturn_id": st.id,
                                "index": idx,
                                "exchange": exchange_payload(ex),
                            },
                        )
                    )
                    hashes.append(h)
                elif hashes[idx] != h:
                    events.append(
                        (
                            EVT_EXCHANGE_RECORDED,
                            {
                                "subturn_id": st.id,
                                "index": idx,
                                "exchange": exchange_payload(ex),
                            },
                        )
                    )
                    hashes[idx] = h

            if st.detailed_summary is not None and sc["summary"] != st.detailed_summary:
                events.append(
                    (
                        EVT_SUBTURN_SUMMARY_SET,
                        {"subturn_id": st.id, "detailed_summary": st.detailed_summary},
                    )
                )
                sc["summary"] = st.detailed_summary

        if turn.completed and not tc["completed"]:
            events.append((EVT_TURN_COMPLETED, turn_completed_payload(turn)))
            tc["completed"] = True

    # Session-global live todo list (last-writer-wins). Only emit once it has
    # ever been non-empty, so sessions that never use todos stay event-free.
    todo_items = session.session_data.get("todo_list") or []
    todo_h = todo_list_hash(todo_items)
    if cursor.get("todo_hash") != todo_h and (todo_items or cursor.get("todo_hash")):
        events.append((EVT_TODO_LIST_SET, {"items": todo_items}))
        cursor["todo_hash"] = todo_h

    return events


def build_cursor(session: Session) -> dict:
    """Build a cursor that marks the entire Session as already-persisted.

    Used after a cold reload to resync the cursor with the durable event log so
    the next save emits only genuine deltas.
    """
    cursor: dict = {}
    compute_events(session, cursor)  # discard events; keep the populated cursor
    return cursor
