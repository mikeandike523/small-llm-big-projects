"""MySQL access for the chat history cache (migration v18).

`chat_turn_index` (one row per turn) and `chat_history_cache` (one row per
subturn) are keyed projections of `session_events`; see
`src/utils/session_cache_projection.py` for how rows map to the session model.
Every query here is served by a primary or unique key: no JSON is searched.

Writes that change a session's events go through :func:`persist_save`, which
commits the events, the cache rows and the session_meta upsert together, so the
cache can never disagree with the event log it describes.
"""

from __future__ import annotations

from typing import Sequence

from src.data import get_pool
from src.utils.sql.session_store_db import (
    execute_insert_events,
    execute_upsert_session_meta,
)

_TURN_COLS = "turn_seq, turn_id, start_event_id, title, completed"
_SUBTURN_COLS = (
    "turn_seq, subturn_seq, subturn_id, user_text, user_text_with_context, "
    "final_response, detailed_summary, is_continuation, approval_mode, origin"
)


def _turn_row(r: dict) -> dict:
    return {
        "turn_seq": int(r["turn_seq"]),
        "turn_id": r["turn_id"],
        "start_event_id": int(r["start_event_id"]),
        "title": r.get("title"),
        "completed": bool(r.get("completed")),
    }


def _fetch(sql: str, params: Sequence) -> list[dict]:
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def load_history_flags(session_id: str) -> dict | None:
    """`{schema_version, history_cache_compatible}` from session_meta (slim)."""
    rows = _fetch(
        "SELECT schema_version, history_cache_compatible FROM session_meta "
        "WHERE session_id = %s",
        (session_id,),
    )
    if not rows:
        return None
    return {
        "schema_version": int(rows[0]["schema_version"] or 0),
        "history_cache_compatible": bool(rows[0]["history_cache_compatible"]),
    }


def latest_turn_upto(session_id: str, cutoff: int) -> dict | None:
    """The last turn whose turn_started id is <= cutoff (its turn_seq = count).

    Walks the primary key backwards, so it normally reads one or two rows.
    """
    rows = _fetch(
        f"SELECT {_TURN_COLS} FROM chat_turn_index "
        "WHERE session_id = %s AND start_event_id <= %s "
        "ORDER BY turn_seq DESC LIMIT 1",
        (session_id, cutoff),
    )
    return _turn_row(rows[0]) if rows else None


def load_turn_rows(session_id: str, first_seq: int, last_seq: int) -> list[dict]:
    """Index rows with first_seq <= turn_seq <= last_seq, in turn order."""
    rows = _fetch(
        f"SELECT {_TURN_COLS} FROM chat_turn_index "
        "WHERE session_id = %s AND turn_seq BETWEEN %s AND %s ORDER BY turn_seq",
        (session_id, first_seq, last_seq),
    )
    return [_turn_row(r) for r in rows]


def load_last_turn_rows(session_id: str, count: int) -> list[dict]:
    """The session's last `count` index rows, in turn order."""
    rows = _fetch(
        f"SELECT {_TURN_COLS} FROM chat_turn_index "
        "WHERE session_id = %s ORDER BY turn_seq DESC LIMIT %s",
        (session_id, count),
    )
    return [_turn_row(r) for r in reversed(rows)]


def turn_seq_for_turn_id(session_id: str, turn_id: str) -> int | None:
    rows = _fetch(
        "SELECT turn_seq FROM chat_turn_index WHERE session_id = %s AND turn_id = %s",
        (session_id, turn_id),
    )
    return int(rows[0]["turn_seq"]) if rows else None


def load_cached_history(
    session_id: str, below_turn_seq: int
) -> list[tuple[dict, list[dict]]]:
    """Every turn before `below_turn_seq` with its subturn rows, in order.

    Two primary-key range scans; no event payload is read.
    """
    turns = _fetch(
        f"SELECT {_TURN_COLS} FROM chat_turn_index "
        "WHERE session_id = %s AND turn_seq < %s ORDER BY turn_seq",
        (session_id, below_turn_seq),
    )
    subturns = _fetch(
        f"SELECT {_SUBTURN_COLS} FROM chat_history_cache "
        "WHERE session_id = %s AND turn_seq < %s ORDER BY turn_seq, subturn_seq",
        (session_id, below_turn_seq),
    )
    by_turn: dict[int, list[dict]] = {}
    for row in subturns:
        by_turn.setdefault(int(row["turn_seq"]), []).append(row)
    return [(_turn_row(t), by_turn.get(int(t["turn_seq"]), [])) for t in turns]


def list_uncached_session_ids() -> list[str]:
    """Sessions whose cache has not been built yet, oldest first."""
    rows = _fetch(
        "SELECT session_id FROM session_meta "
        "WHERE history_cache_compatible = 0 ORDER BY created_at",
        (),
    )
    return [r["session_id"] for r in rows]


def list_all_session_ids() -> list[str]:
    """Every session, oldest first."""
    rows = _fetch("SELECT session_id FROM session_meta ORDER BY created_at", ())
    return [r["session_id"] for r in rows]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _execute_upsert_turn_rows(
    cur, session_id: str, turn_rows: Sequence[dict], starts: dict[str, int]
) -> None:
    for row in turn_rows:
        start = row.get("start_event_id") or starts.get(row["turn_id"])
        if start is None:
            # The turn's row already exists (its turn_started was saved
            # earlier); only the mutable fields change.
            cur.execute(
                "UPDATE chat_turn_index SET title = %s, completed = %s "
                "WHERE session_id = %s AND turn_id = %s",
                (row["title"], int(row["completed"]), session_id, row["turn_id"]),
            )
            continue
        cur.execute(
            "INSERT INTO chat_turn_index "
            "(session_id, turn_seq, turn_id, start_event_id, title, completed) "
            "VALUES (%s, %s, %s, %s, %s, %s) AS incoming "
            "ON DUPLICATE KEY UPDATE title = incoming.title, "
            "completed = incoming.completed",
            (
                session_id,
                row["turn_seq"],
                row["turn_id"],
                start,
                row["title"],
                int(row["completed"]),
            ),
        )


def _execute_upsert_subturn_rows(
    cur, session_id: str, subturn_rows: Sequence[dict]
) -> None:
    if not subturn_rows:
        return
    cur.executemany(
        "INSERT INTO chat_history_cache "
        f"(session_id, {_SUBTURN_COLS}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS incoming "
        "ON DUPLICATE KEY UPDATE "
        "user_text = incoming.user_text, "
        "user_text_with_context = incoming.user_text_with_context, "
        "final_response = incoming.final_response, "
        "detailed_summary = incoming.detailed_summary, "
        "is_continuation = incoming.is_continuation, "
        "approval_mode = incoming.approval_mode, "
        "origin = incoming.origin",
        [
            (
                session_id,
                r["turn_seq"],
                r["subturn_seq"],
                r["subturn_id"],
                r["user_text"],
                r["user_text_with_context"],
                r["final_response"],
                r["detailed_summary"],
                int(r["is_continuation"]),
                r["approval_mode"],
                r["origin"],
            )
            for r in subturn_rows
        ],
    )


def persist_save(
    session_id: str,
    events: Sequence[tuple[str, dict]],
    turn_rows: Sequence[dict],
    subturn_rows: Sequence[dict],
    meta: dict,
) -> None:
    """Append events, update the cache rows and upsert session_meta atomically.

    `turn_rows` whose `start_event_id` is None take the id of their
    `turn_started` event from `events`, or (if it was saved earlier) only
    update title/completed. Pass empty row lists for a session whose cache is
    not built yet. `meta` holds `execute_upsert_session_meta`'s keyword
    arguments.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            starts = execute_insert_events(cur, session_id, events) if events else {}
            # The meta row first: a brand-new session's cache rows reference it.
            execute_upsert_session_meta(cur, session_id, **meta)
            _execute_upsert_turn_rows(cur, session_id, turn_rows, starts)
            _execute_upsert_subturn_rows(cur, session_id, subturn_rows)
        conn.commit()


def replace_session_cache(
    session_id: str, turn_rows: Sequence[dict], subturn_rows: Sequence[dict]
) -> None:
    """Rebuild a session's cache and mark it compatible, in one transaction.

    Used by the fill-session-cache backfill: any partial rows are deleted
    first, and the flag is only set if every insert succeeds.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chat_history_cache WHERE session_id = %s", (session_id,)
            )
            cur.execute(
                "DELETE FROM chat_turn_index WHERE session_id = %s", (session_id,)
            )
            _execute_upsert_turn_rows(cur, session_id, turn_rows, {})
            _execute_upsert_subturn_rows(cur, session_id, subturn_rows)
            cur.execute(
                "UPDATE session_meta SET history_cache_compatible = 1 "
                "WHERE session_id = %s",
                (session_id,),
            )
        conn.commit()


def append_setting_event(
    session_id: str, event_type: str, payload: dict, meta_updates: dict
) -> None:
    """Append one session-level settings event (+ session_meta copies) atomically.

    `meta_updates` maps session_meta columns to new values; the column names
    come from code, never from user input.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            execute_insert_events(cur, session_id, [(event_type, payload)])
            if meta_updates:
                assignments = ", ".join(f"{col} = %s" for col in meta_updates)
                cur.execute(
                    f"UPDATE session_meta SET {assignments} WHERE session_id = %s",
                    (*meta_updates.values(), session_id),
                )
        conn.commit()
