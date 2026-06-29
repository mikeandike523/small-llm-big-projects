"""Durable session persistence in MySQL (the `sessions` table, migration v10).

MySQL is the source of truth for sessions; Redis is a hot write-through cache.
These helpers each acquire their own pooled connection and commit writes, so
callers (session_store.py) don't have to manage transactions.

JSON columns (`data`, `memory_json`) are stored as json.dumps strings and may
come back from the driver as either str or already-decoded objects, so reads
normalize both (mirrors KVManager._normalize_json).
"""

from __future__ import annotations

import json
from typing import Any

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


def upsert_session(
    session_id: str,
    *,
    data: dict,
    memory: dict,
    schema_version: int,
    profile_name: str | None,
    initial_cwd: str,
    current_cwd: str | None,
    total_cost_usd: float,
) -> None:
    """Insert or update the durable row for a session."""
    data_json = json.dumps(data, ensure_ascii=False)
    memory_json = json.dumps(memory, ensure_ascii=False)
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (
                    session_id, schema_version, profile_name, initial_cwd,
                    current_cwd, total_cost_usd, data, memory_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) AS incoming
                ON DUPLICATE KEY UPDATE
                    schema_version = incoming.schema_version,
                    profile_name   = incoming.profile_name,
                    initial_cwd    = incoming.initial_cwd,
                    current_cwd    = incoming.current_cwd,
                    total_cost_usd = incoming.total_cost_usd,
                    data           = incoming.data,
                    memory_json    = incoming.memory_json
                """,
                (
                    session_id,
                    schema_version,
                    profile_name,
                    initial_cwd,
                    current_cwd,
                    total_cost_usd,
                    data_json,
                    memory_json,
                ),
            )
        conn.commit()


def load_session_row(session_id: str) -> dict | None:
    """Return the durable row for a session, or None if absent.

    `data` and `memory_json` are returned as decoded Python objects under the
    keys `data` and `memory`.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                """
                SELECT session_id, schema_version, profile_name, initial_cwd,
                       current_cwd, total_cost_usd, data, memory_json
                FROM sessions WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "session_id": row["session_id"],
        "schema_version": row["schema_version"],
        "profile_name": row["profile_name"],
        "initial_cwd": row["initial_cwd"],
        "current_cwd": row["current_cwd"],
        "total_cost_usd": row["total_cost_usd"],
        "data": _normalize_json(row["data"]) or {},
        "memory": _normalize_json(row["memory_json"]) or {},
    }


def list_session_rows() -> list[dict]:
    """Return all sessions (newest first) with the full `data` blob decoded.

    Used by the dashboard list endpoint; `memory_json` is intentionally not
    fetched here to keep the payload light.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                """
                SELECT session_id, schema_version, profile_name, initial_cwd,
                       current_cwd, total_cost_usd, data, created_at
                FROM sessions ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "session_id": row["session_id"],
                "schema_version": row["schema_version"],
                "profile_name": row["profile_name"],
                "initial_cwd": row["initial_cwd"],
                "current_cwd": row["current_cwd"],
                "total_cost_usd": row["total_cost_usd"],
                "created_at": row["created_at"],
                "data": _normalize_json(row["data"]) or {},
            }
        )
    return results


def delete_session_row(session_id: str) -> None:
    """Delete the durable row for a session (no-op if absent)."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
        conn.commit()
