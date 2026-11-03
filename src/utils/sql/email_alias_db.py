"""session_meta email-alias claims (written only via setting_events)."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass

from src.data import get_pool

MYSQL_DUPLICATE_KEY_ERRNO = 1062


@dataclass(frozen=True)
class AliasClaim:
    session_id: str
    alias: str
    enabled: bool
    claimed_at: float | None
    created_at: float


def is_duplicate_key_error(exc: BaseException) -> bool:
    return getattr(exc, "errno", None) == MYSQL_DUPLICATE_KEY_ERRNO


def find_alias_owner(alias: str, *, exclude_session_id: str) -> dict | None:
    """Another session holding ``alias`` (earliest first), or None."""
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT session_id, recent_task_titles FROM session_meta
            WHERE email_alias = %s AND session_id <> %s
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (alias, exclude_session_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    titles = row.get("recent_task_titles")
    if isinstance(titles, str):
        try:
            titles = json.loads(titles)
        except ValueError:
            titles = []
    title = titles[-1] if isinstance(titles, list) and titles else None
    return {"session_id": row["session_id"], "title": title}


def list_alias_claims(aliases: Collection[str]) -> list[AliasClaim]:
    """Claims for the given normalized aliases, earliest session first."""
    wanted = sorted(set(aliases))
    if not wanted:
        return []
    placeholders = ", ".join(["%s"] * len(wanted))
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"""
            SELECT session_id, email_alias, email_enabled, email_alias_claimed_at,
                   created_at
            FROM session_meta
            WHERE email_alias IN ({placeholders})
            ORDER BY created_at ASC, session_id ASC
            """,
            tuple(wanted),
        )
        rows = cur.fetchall()
    return [_row_to_claim(row) for row in rows]


def list_all_claimed_aliases() -> set[str]:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT email_alias FROM session_meta WHERE email_alias IS NOT NULL"
        )
        rows = cur.fetchall()
    return {str(row[0]) for row in rows}


def _row_to_claim(row: dict) -> AliasClaim:
    claimed_at = row.get("email_alias_claimed_at")
    return AliasClaim(
        session_id=str(row["session_id"]),
        alias=str(row["email_alias"]),
        enabled=bool(row.get("email_enabled")),
        claimed_at=float(claimed_at) if claimed_at is not None else None,
        created_at=float(row.get("created_at") or 0.0),
    )
