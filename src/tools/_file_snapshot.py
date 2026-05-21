from __future__ import annotations

import hashlib
import os


_processed: dict[str, set[str]] = {}  # session_id -> set[norm_path]


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _path_hash(norm_path: str) -> bytes:
    return hashlib.sha256(norm_path.encode("utf-8")).digest()


def _next_order(cursor, session_id: str, path_hash: bytes) -> int:
    cursor.execute(
        "SELECT COALESCE(MAX(snapshot_order), -1) + 1 FROM file_snapshots"
        " WHERE session_id=%s AND file_path_hash=%s",
        (session_id, path_hash),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def take_snapshot(session_id: str, path: str, content: str) -> int:
    """Save content as a new snapshot for path in this session. Returns snapshot_order."""
    from src.data import get_pool

    norm = _norm(path)
    ph = _path_hash(norm)
    pool = get_pool()
    conn = pool.get_connection()
    try:
        with conn.cursor() as cur:
            order = _next_order(cur, session_id, ph)
            cur.execute(
                "INSERT INTO file_snapshots"
                " (session_id, file_path, file_path_hash, content, snapshot_order)"
                " VALUES (%s, %s, %s, %s, %s)",
                (session_id, norm, ph, content, order),
            )
        conn.commit()
        return order
    finally:
        conn.close()


def auto_snapshot_if_first_write(session_id: str, path: str) -> None:
    """Take a snapshot of path before its first write this session, if file exists."""
    norm = _norm(path)
    session_processed = _processed.setdefault(session_id, set())
    if norm in session_processed:
        return
    session_processed.add(norm)
    if not os.path.isfile(norm):
        return
    try:
        with open(norm, "r", encoding="utf-8", newline="") as fh:
            content = fh.read()
        take_snapshot(session_id, norm, content)
    except Exception:
        pass


def list_snapshots(session_id: str, path: str) -> list[dict]:
    """Return list of snapshot metadata dicts for a path, ordered by snapshot_order."""
    from src.data import get_pool

    norm = _norm(path)
    ph = _path_hash(norm)
    pool = get_pool()
    conn = pool.get_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, snapshot_order, created_at FROM file_snapshots"
                " WHERE session_id=%s AND file_path_hash=%s"
                " ORDER BY snapshot_order ASC",
                (session_id, ph),
            )
            return list(cur.fetchall())
    finally:
        conn.close()


def get_snapshot(session_id: str, path: str, snapshot_order: int) -> str | None:
    """Return content of a specific snapshot, or None if not found."""
    from src.data import get_pool

    norm = _norm(path)
    ph = _path_hash(norm)
    pool = get_pool()
    conn = pool.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM file_snapshots"
                " WHERE session_id=%s AND file_path_hash=%s AND snapshot_order=%s",
                (session_id, ph, snapshot_order),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    finally:
        conn.close()


def clear_session(session_id: str) -> None:
    _processed.pop(session_id, None)
