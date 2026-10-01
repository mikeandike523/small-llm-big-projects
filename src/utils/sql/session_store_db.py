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


def append_events(session_id: str, events: Sequence[tuple[str, dict]]) -> None:
    """Append (event_type, payload) tuples to the session's event log."""
    if not events:
        return
    rows = [
        (session_id, event_type, json.dumps(payload, ensure_ascii=False))
        for event_type, payload in events
    ]
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO session_events (session_id, event_type, payload) "
                "VALUES (%s, %s, %s)",
                rows,
            )
        conn.commit()


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

    Every turn has exactly one `turn_started` event, so these ids also bound
    each turn's events: turn N's events lie in [start_N, start_N+1). Served by
    idx_events_type (session_id, event_type), which InnoDB extends with the
    primary key, so the ORDER BY needs no sort.
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
    return [(int(r["id"]), r["turn_id"]) for r in rows]


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


def load_latest_event_payload(session_id: str, event_type: str) -> dict | None:
    """Return the payload of the session's newest event of `event_type`."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT payload FROM session_events "
                "WHERE session_id = %s AND event_type = %s "
                "ORDER BY id DESC LIMIT 1",
                (session_id, event_type),
            )
            row = cur.fetchone()
    return _normalize_json(row["payload"]) if row else None


# ---------------------------------------------------------------------------
# session_meta (slim per-session row)
# ---------------------------------------------------------------------------


def upsert_session_meta(
    session_id: str,
    *,
    created_at: float,
    schema_version: int,
    profile_name: str | None,
    initial_cwd: str,
    current_cwd: str | None,
    total_cost_usd: float,
    turn_count: int,
    task_titles: list,
    interim_response_as_thinking: bool,
    load_custom_skills_tools: bool,
    memory: dict,
    heartbeat_enabled: bool = False,
    last_context_usage: dict | None = None,
) -> None:
    """Insert or update the slim metadata row for a session.

    `created_at` is set only on insert (it's the authoritative session
    wall-clock); subsequent upserts leave it untouched.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_meta (
                    session_id, created_at, schema_version, profile_name,
                    initial_cwd, current_cwd, total_cost_usd, turn_count,
                    task_titles, interim_response_as_thinking,
                    load_custom_skills_tools, corrupt, memory_json, last_context_usage,
                    heartbeat_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
                AS incoming
                ON DUPLICATE KEY UPDATE
                    schema_version               = incoming.schema_version,
                    profile_name                 = incoming.profile_name,
                    initial_cwd                  = incoming.initial_cwd,
                    current_cwd                  = incoming.current_cwd,
                    total_cost_usd               = incoming.total_cost_usd,
                    turn_count                   = incoming.turn_count,
                    task_titles                  = incoming.task_titles,
                    interim_response_as_thinking = incoming.interim_response_as_thinking,
                    load_custom_skills_tools     = incoming.load_custom_skills_tools,
                    corrupt                      = 0,
                    memory_json                  = incoming.memory_json,
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
                    json.dumps(task_titles, ensure_ascii=False),
                    1 if interim_response_as_thinking else 0,
                    1 if load_custom_skills_tools else 0,
                    json.dumps(memory, ensure_ascii=False),
                    (
                        json.dumps(last_context_usage)
                        if last_context_usage is not None
                        else None
                    ),
                    1 if heartbeat_enabled else 0,
                ),
            )
        conn.commit()


# Columns selected for the dashboard list — deliberately excludes memory_json so
# the list query stays light and never filesorts over large blobs.
_META_LIST_COLS = (
    "session_id, created_at, schema_version, profile_name, initial_cwd, "
    "current_cwd, total_cost_usd, turn_count, task_titles, "
    "interim_response_as_thinking, load_custom_skills_tools, corrupt, "
    "heartbeat_enabled"
)


def _row_to_meta(row: dict, *, include_memory: bool) -> dict:
    meta = {
        "session_id": row["session_id"],
        "created_at": float(row.get("created_at") or 0.0),
        "schema_version": row.get("schema_version", 0),
        "profile_name": row.get("profile_name"),
        "initial_cwd": row.get("initial_cwd") or "",
        "current_cwd": row.get("current_cwd"),
        "total_cost_usd": float(row.get("total_cost_usd") or 0.0),
        "turn_count": row.get("turn_count", 0),
        "task_titles": _normalize_json(row.get("task_titles")) or [],
        "interim_response_as_thinking": bool(row.get("interim_response_as_thinking")),
        "load_custom_skills_tools": bool(row.get("load_custom_skills_tools")),
        "corrupt": bool(row.get("corrupt")),
        "last_context_usage": _normalize_json(row.get("last_context_usage")),
        "heartbeat_enabled": bool(row.get("heartbeat_enabled")),
    }
    if include_memory:
        meta["memory"] = _normalize_json(row.get("memory_json")) or {}
    return meta


def list_session_meta() -> list[dict]:
    """Return slim metadata for all sessions, newest first."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                f"SELECT {_META_LIST_COLS} FROM session_meta ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    return [_row_to_meta(r, include_memory=False) for r in rows]


def load_session_meta(session_id: str) -> dict | None:
    """Return the metadata row for one session (including the memory snapshot)."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                f"SELECT {_META_LIST_COLS}, memory_json, last_context_usage "
                "FROM session_meta WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return _row_to_meta(row, include_memory=True)


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
