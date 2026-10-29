"""Durable state access for Gmail watch registration and renewal."""

from __future__ import annotations

from dataclasses import dataclass

from src.data import get_pool


@dataclass(frozen=True)
class GmailWatchState:
    last_attempt_unix: float | None
    last_success_unix: float | None
    watch_expiration_ms: int | None
    renewal_history_id: str | None
    last_error: str | None


def load_gmail_watch_state() -> GmailWatchState:
    """Load the singleton renewal row created by structure migration v20."""
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute("""
            SELECT last_attempt_unix, last_success_unix,
                   watch_expiration_ms, renewal_history_id, last_error
            FROM gmail_watch_state
            WHERE singleton_id = 1
            """)
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            "gmail_watch_state is missing its singleton row; run structure migration v20"
        )
    return GmailWatchState(
        last_attempt_unix=(
            float(row["last_attempt_unix"])
            if row["last_attempt_unix"] is not None
            else None
        ),
        last_success_unix=(
            float(row["last_success_unix"])
            if row["last_success_unix"] is not None
            else None
        ),
        watch_expiration_ms=(
            int(row["watch_expiration_ms"])
            if row["watch_expiration_ms"] is not None
            else None
        ),
        renewal_history_id=(
            str(row["renewal_history_id"])
            if row["renewal_history_id"] is not None
            else None
        ),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
    )
