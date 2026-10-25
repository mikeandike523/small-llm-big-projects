"""Durable session persistence in MySQL (event-sourced, migration v11).

MySQL is the source of truth; Redis is a hot write-through cache. Sessions are
stored as two tables:

  session_meta    one slim row per session (drives the cheap dashboard list and
                  holds per-session state: cwd, cost, schema, the session_memory
                  hash snapshot, and denormalized list metadata).
  session_events  append-only semantic event log; a Session is reconstructed by
                  selecting its events in `id` order and replaying them.

These helpers each acquire their own pooled connection and commit writes, so
callers don't manage transactions. JSON columns may come back from the driver as
either str or already-decoded objects, so reads normalize both.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from src.data import get_pool


def _normalize_json(value: object) -> Any:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


# ---------------------------------------------------------------------------
# session_events (append-only log)
# ---------------------------------------------------------------------------


_INSERT_EVENT_SQL = (
    "INSERT INTO session_events (session_id, event_type, payload) VALUES (%s, %s, %s)"
)


def execute_insert_events(
    cur, session_id: str, events: Sequence[tuple[str, dict]]
) -> dict[str, int]:
    """Insert events in order on an open cursor (caller commits).

    Returns `{turn_id: event id}` for each `turn_started` event. Those rows are
    inserted on their own so `lastrowid` is exactly their id (a batched insert
    does not guarantee consecutive ids).
    """
    starts: dict[str, int] = {}
    batch: list[tuple] = []
    for event_type, payload in events:
        row = (session_id, event_type, json.dumps(payload, ensure_ascii=False))
        if event_type == "turn_started":
            if batch:
                cur.executemany(_INSERT_EVENT_SQL, batch)
                batch = []
            cur.execute(_INSERT_EVENT_SQL, row)
            starts[payload["turn_id"]] = int(cur.lastrowid)
        else:
            batch.append(row)
    if batch:
        cur.executemany(_INSERT_EVENT_SQL, batch)
    return starts


def load_session_events(session_id: str) -> list[dict]:
    """Return all events for a session in replay order (each: type + payload)."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT event_type, payload FROM session_events "
                "WHERE session_id = %s ORDER BY id",
                (session_id,),
            )
            rows = cur.fetchall()
    return [
        {"event_type": r["event_type"], "payload": _normalize_json(r["payload"])}
        for r in rows
    ]


def list_turn_starts(session_id: str) -> list[tuple[int, str]]:
    """Return `(event id, turn_id)` for each turn, in turn order.

    Reads every `turn_started` payload: only for sessions without a built chat
    history cache (cached sessions read `chat_turn_index`). Served by
    idx_events_type (session_id, event_type), which InnoDB extends with the
    primary key, so the ORDER BY needs no sort.

    A turn id is listed once, at its first `turn_started`: the pre-2026-10-25
    save path could re-write a whole session (cursor lost), repeating every
    turn's events. Turn N's own events still lie in [start_N, start_N+1); the
    page assembler skips the repeated events of other turns in that range.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id')) AS turn_id "
                "FROM session_events "
                "WHERE session_id = %s AND event_type = 'turn_started' ORDER BY id",
                (session_id,),
            )
            rows = cur.fetchall()
    seen: set[str] = set()
    starts = []
    for r in rows:
        if r["turn_id"] not in seen:
            seen.add(r["turn_id"])
            starts.append((int(r["id"]), r["turn_id"]))
    return starts


def max_event_id(session_id: str) -> int:
    """Return the session's highest event id (0 if it has no events)."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(id) FROM session_events WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def load_event_page(
    session_id: str, after_id: int, upto_id: int, limit: int
) -> list[dict]:
    """Return up to `limit` events with after_id < id <= upto_id, in id order."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, event_type, payload FROM session_events "
                "WHERE session_id = %s AND id > %s AND id <= %s "
                "ORDER BY id LIMIT %s",
                (session_id, after_id, upto_id, limit),
            )
            rows = cur.fetchall()
    return [
        {
            "id": int(r["id"]),
            "event_type": r["event_type"],
            "payload": _normalize_json(r["payload"]),
        }
        for r in rows
    ]


def load_latest_event_payload(
    session_id: str, event_type: str, *, upto_id: int | None = None
) -> dict | None:
    """Return the payload of the session's newest event of `event_type`.

    With `upto_id`, only events with id <= upto_id are considered.
    """
    sql = (
        "SELECT payload FROM session_events "
        "WHERE session_id = %s AND event_type = %s"
    )
    params: tuple = (session_id, event_type)
    if upto_id is not None:
        sql += " AND id <= %s"
        params += (upto_id,)
    sql += " ORDER BY id DESC LIMIT 1"
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    return _normalize_json(row["payload"]) if row else None


def load_latest_event_rows(
    session_id: str, event_types: Sequence[str], *, upto_id: int | None = None
) -> list[dict]:
    """Return the newest event row of each type, in id order, ready for replay.

    One keyed lookup per type on idx_events_type (session_id, event_type, +id),
    unioned into one round trip. Absent types are skipped.
    """
    if not event_types:
        return []
    bound = " AND id <= %s" if upto_id is not None else ""
    part = (
        "(SELECT id, event_type, payload FROM session_events "
        f"WHERE session_id = %s AND event_type = %s{bound} ORDER BY id DESC LIMIT 1)"
    )
    params: list = []
    for event_type in event_types:
        params.extend([session_id, event_type])
        if upto_id is not None:
            params.append(upto_id)
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(" UNION ALL ".join([part] * len(event_types)), params)
            rows = cur.fetchall()
    return sorted(
        (
            {
                "id": int(r["id"]),
                "event_type": r["event_type"],
                "payload": _normalize_json(r["payload"]),
            }
            for r in rows
        ),
        key=lambda r: r["id"],
    )


# ---------------------------------------------------------------------------
# subturn_thinking_chars (display metadata, migration v17)
# ---------------------------------------------------------------------------


def add_thinking_chars(
    session_id: str, subturn_id: str, native_chars: int, irat_chars: int
) -> None:
    """Add streamed thinking-delta counts to a subturn's running totals."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subturn_thinking_chars
                    (session_id, subturn_id, native_chars, irat_chars)
                VALUES (%s, %s, %s, %s)
                AS incoming
                ON DUPLICATE KEY UPDATE
                    native_chars = subturn_thinking_chars.native_chars
                        + incoming.native_chars,
                    irat_chars = subturn_thinking_chars.irat_chars
                        + incoming.irat_chars
                """,
                (session_id, subturn_id, native_chars, irat_chars),
            )
        conn.commit()


def load_thinking_char_counts(
    session_id: str, subturn_ids: list[str]
) -> dict[str, tuple[int, int]]:
    """Return `{subturn_id: (native_chars, irat_chars)}` for those subturns."""
    if not subturn_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(subturn_ids))
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT subturn_id, native_chars, irat_chars "
                "FROM subturn_thinking_chars "
                f"WHERE session_id = %s AND subturn_id IN ({placeholders})",
                (session_id, *subturn_ids),
            )
            rows = cur.fetchall()
    return {
        r["subturn_id"]: (int(r["native_chars"]), int(r["irat_chars"])) for r in rows
    }


# ---------------------------------------------------------------------------
# session_meta (slim per-session row)
# ---------------------------------------------------------------------------


def execute_upsert_session_meta(
    cur,
    session_id: str,
    *,
    created_at: float,
    schema_version: int,
    profile_name: str | None,
    initial_cwd: str,
    current_cwd: str | None,
    total_cost_usd: float,
    turn_count: int,
    recent_task_titles: list,
    task_title_count: int,
    interim_response_as_thinking: bool,
    load_custom_skills_tools: bool,
    heartbeat_enabled: bool = False,
    last_context_usage: dict | None = None,
) -> None:
    """Run the session_meta upsert on an open cursor (caller commits).

    `created_at` is set only on insert (it's the authoritative session
    wall-clock); subsequent upserts leave it untouched. So is
    `history_cache_compatible`: a new row takes the column default (1), and an
    existing row keeps its value.
    """
    cur.execute(
        """
        INSERT INTO session_meta (
            session_id, created_at, schema_version, profile_name,
            initial_cwd, current_cwd, total_cost_usd, turn_count,
            recent_task_titles, task_title_count, interim_response_as_thinking,
            load_custom_skills_tools, corrupt, last_context_usage,
            heartbeat_enabled
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
        AS incoming
        ON DUPLICATE KEY UPDATE
            schema_version               = incoming.schema_version,
            profile_name                 = incoming.profile_name,
            initial_cwd                  = incoming.initial_cwd,
            current_cwd                  = incoming.current_cwd,
            total_cost_usd               = incoming.total_cost_usd,
            turn_count                   = incoming.turn_count,
            recent_task_titles           = incoming.recent_task_titles,
            task_title_count             = incoming.task_title_count,
            interim_response_as_thinking = incoming.interim_response_as_thinking,
            load_custom_skills_tools     = incoming.load_custom_skills_tools,
            corrupt                      = 0,
            last_context_usage           = incoming.last_context_usage,
            heartbeat_enabled            = incoming.heartbeat_enabled
        """,
        (
            session_id,
            float(created_at or 0.0),
            schema_version,
            profile_name,
            initial_cwd,
            current_cwd,
            float(total_cost_usd or 0.0),
            turn_count,
            json.dumps(recent_task_titles, ensure_ascii=False),
            int(task_title_count),
            1 if interim_response_as_thinking else 0,
            1 if load_custom_skills_tools else 0,
            (
                json.dumps(last_context_usage)
                if last_context_usage is not None
                else None
            ),
            1 if heartbeat_enabled else 0,
        ),
    )


# Columns selected for the dashboard list (light: no large blobs).
_META_LIST_COLS = (
    "session_id, created_at, schema_version, profile_name, initial_cwd, "
    "current_cwd, total_cost_usd, turn_count, recent_task_titles, "
    "task_title_count, interim_response_as_thinking, load_custom_skills_tools, "
    "corrupt, heartbeat_enabled, history_cache_compatible"
)


def _row_to_meta(row: dict) -> dict:
    return {
        "session_id": row["session_id"],
        "created_at": float(row.get("created_at") or 0.0),
        "schema_version": row.get("schema_version", 0),
        "profile_name": row.get("profile_name"),
        "initial_cwd": row.get("initial_cwd") or "",
        "current_cwd": row.get("current_cwd"),
        "total_cost_usd": float(row.get("total_cost_usd") or 0.0),
        "turn_count": row.get("turn_count", 0),
        "recent_task_titles": _normalize_json(row.get("recent_task_titles")) or [],
        "task_title_count": int(row.get("task_title_count") or 0),
        "interim_response_as_thinking": bool(row.get("interim_response_as_thinking")),
        "load_custom_skills_tools": bool(row.get("load_custom_skills_tools")),
        "corrupt": bool(row.get("corrupt")),
        "last_context_usage": _normalize_json(row.get("last_context_usage")),
        "heartbeat_enabled": bool(row.get("heartbeat_enabled")),
        "history_cache_compatible": bool(row.get("history_cache_compatible")),
    }


def list_session_meta() -> list[dict]:
    """Return slim metadata for all sessions, newest first."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                f"SELECT {_META_LIST_COLS} FROM session_meta ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    return [_row_to_meta(r) for r in rows]


def load_session_meta(session_id: str) -> dict | None:
    """Return the metadata row for one session."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                f"SELECT {_META_LIST_COLS}, last_context_usage "
                "FROM session_meta WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return _row_to_meta(row)


# ---------------------------------------------------------------------------
# heartbeat_last_runs (durable scheduler state)
# ---------------------------------------------------------------------------


def load_heartbeat_last_runs() -> dict[str, float]:
    """Return the durable session_id -> last-run Unix timestamp mapping."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute("SELECT session_id, last_run_unix FROM heartbeat_last_runs")
            rows = cur.fetchall()
    return {row["session_id"]: float(row["last_run_unix"]) for row in rows}


def upsert_heartbeat_last_run(session_id: str, last_run_unix: float) -> None:
    """Durably record a session's most recent successful heartbeat run."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO heartbeat_last_runs (session_id, last_run_unix)
                VALUES (%s, %s) AS incoming
                ON DUPLICATE KEY UPDATE
                    last_run_unix = incoming.last_run_unix
                """,
                (session_id, float(last_run_unix)),
            )
        conn.commit()


def mark_session_corrupt(session_id: str) -> None:
    """Flag a session whose events failed to replay (best-effort, no-op if absent)."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE session_meta SET corrupt = 1 WHERE session_id = %s",
                (session_id,),
            )
        conn.commit()


def delete_sessions(session_ids: Sequence[str]) -> int:
    """Delete many sessions' metadata rows and events in a single transaction.

    Deletes each session's events first, then its metadata row. Returns the
    number of sessions passed in (the deletes are no-ops for absent sessions).
    """
    ids = list(session_ids)
    if not ids:
        return 0

    id_tuples = [(session_id,) for session_id in ids]
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "DELETE FROM session_events WHERE session_id = %s", id_tuples
            )
            cur.executemany("DELETE FROM session_meta WHERE session_id = %s", id_tuples)
        conn.commit()
    return len(ids)


def delete_session(session_id: str) -> None:
    """Delete a session's metadata row and all of its events (no-op if absent)."""
    delete_sessions([session_id])
