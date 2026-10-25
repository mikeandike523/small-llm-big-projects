"""MySQL access for session memory (`session_memory`, migration v19).

One row per memory key, keyed by (session_id, mem_key). Keys are listed in
key order.
"""

from __future__ import annotations

from src.data import get_pool


def _fetch(sql: str, params: tuple) -> list[dict]:
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _execute(sql: str, params: tuple) -> int:
    """Run one write statement and commit; returns the affected row count."""
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            count = cur.rowcount
        conn.commit()
    return count


def get_memory_value(session_id: str, key: str) -> str | None:
    rows = _fetch(
        "SELECT value FROM session_memory WHERE session_id = %s AND mem_key = %s",
        (session_id, key),
    )
    return rows[0]["value"] if rows else None


def has_memory_key(session_id: str, key: str) -> bool:
    rows = _fetch(
        "SELECT 1 AS found FROM session_memory WHERE session_id = %s AND mem_key = %s",
        (session_id, key),
    )
    return bool(rows)


def list_memory_keys(session_id: str) -> list[str]:
    rows = _fetch(
        "SELECT mem_key FROM session_memory WHERE session_id = %s ORDER BY mem_key",
        (session_id,),
    )
    return [r["mem_key"] for r in rows]


def count_memory_keys(session_id: str) -> int:
    rows = _fetch(
        "SELECT COUNT(*) AS n FROM session_memory WHERE session_id = %s",
        (session_id,),
    )
    return int(rows[0]["n"])


def load_memory(session_id: str) -> dict[str, str]:
    rows = _fetch(
        "SELECT mem_key, value FROM session_memory WHERE session_id = %s "
        "ORDER BY mem_key",
        (session_id,),
    )
    return {r["mem_key"]: r["value"] for r in rows}


def set_memory_value(session_id: str, key: str, value: str) -> None:
    _execute(
        "INSERT INTO session_memory (session_id, mem_key, value) "
        "VALUES (%s, %s, %s) AS incoming "
        "ON DUPLICATE KEY UPDATE value = incoming.value",
        (session_id, key, value),
    )


def add_memory_value(session_id: str, key: str, value: str) -> bool:
    """Insert only if the key is absent; True if it was inserted."""
    return (
        _execute(
            "INSERT IGNORE INTO session_memory (session_id, mem_key, value) "
            "VALUES (%s, %s, %s)",
            (session_id, key, value),
        )
        > 0
    )


def delete_memory_key(session_id: str, key: str) -> bool:
    """Delete one key; True if it existed."""
    return (
        _execute(
            "DELETE FROM session_memory WHERE session_id = %s AND mem_key = %s",
            (session_id, key),
        )
        > 0
    )


def clear_memory(session_id: str) -> None:
    _execute("DELETE FROM session_memory WHERE session_id = %s", (session_id,))
