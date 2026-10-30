"""Durable per-mailbox Gmail synchronization and scheduler state."""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.data import get_pool


@dataclass(frozen=True)
class GmailMailboxState:
    mailbox_email: str
    last_processed_history_id: str | None
    initialization_started_unix: float | None
    watch_last_attempt_unix: float | None
    watch_last_success_unix: float | None
    watch_expiration_ms: int | None
    watch_next_attempt_unix: float | None
    watch_last_error: str | None
    sync_last_attempt_unix: float | None
    sync_last_success_unix: float | None
    sync_last_error: str | None


def ensure_mailbox_state(mailbox_email: str) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT IGNORE INTO gmail_mailbox_state (mailbox_email) VALUES (%s)",
            (mailbox_email,),
        )
        conn.commit()


def load_mailbox_state(mailbox_email: str) -> GmailMailboxState:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT mailbox_email, last_processed_history_id,
                   initialization_started_unix, watch_last_attempt_unix,
                   watch_last_success_unix, watch_expiration_ms,
                   watch_next_attempt_unix,
                   watch_last_error, sync_last_attempt_unix,
                   sync_last_success_unix, sync_last_error
            FROM gmail_mailbox_state WHERE mailbox_email = %s
            """,
            (mailbox_email,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Gmail mailbox state is missing for {mailbox_email}")

    def optional_float(name: str) -> float | None:
        return float(row[name]) if row[name] is not None else None

    def optional_text(name: str) -> str | None:
        return str(row[name]) if row[name] is not None else None

    return GmailMailboxState(
        mailbox_email=str(row["mailbox_email"]),
        last_processed_history_id=optional_text("last_processed_history_id"),
        initialization_started_unix=optional_float("initialization_started_unix"),
        watch_last_attempt_unix=optional_float("watch_last_attempt_unix"),
        watch_last_success_unix=optional_float("watch_last_success_unix"),
        watch_expiration_ms=(
            int(row["watch_expiration_ms"])
            if row["watch_expiration_ms"] is not None
            else None
        ),
        watch_next_attempt_unix=optional_float("watch_next_attempt_unix"),
        watch_last_error=optional_text("watch_last_error"),
        sync_last_attempt_unix=optional_float("sync_last_attempt_unix"),
        sync_last_success_unix=optional_float("sync_last_success_unix"),
        sync_last_error=optional_text("sync_last_error"),
    )


def mark_initialization_started(mailbox_email: str, now: float | None = None) -> None:
    value = time.time() if now is None else now
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_mailbox_state
            SET initialization_started_unix = COALESCE(initialization_started_unix, %s)
            WHERE mailbox_email = %s AND last_processed_history_id IS NULL
            """,
            (value, mailbox_email),
        )
        conn.commit()


def initialize_cursor_if_absent(mailbox_email: str, history_id: str) -> bool:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_mailbox_state
            SET last_processed_history_id = %s
            WHERE mailbox_email = %s AND last_processed_history_id IS NULL
            """,
            (history_id, mailbox_email),
        )
        changed = cur.rowcount == 1
        conn.commit()
    return changed


def advance_cursor(mailbox_email: str, expected: str, next_value: str) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_mailbox_state SET last_processed_history_id = %s
            WHERE mailbox_email = %s AND last_processed_history_id = %s
            """,
            (next_value, mailbox_email, expected),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise RuntimeError("Gmail history cursor changed during synchronization")
        conn.commit()


def record_watch_attempt(mailbox_email: str, now: float) -> None:
    _update(mailbox_email, "watch_last_attempt_unix = %s", (now,))


def record_watch_success(
    mailbox_email: str, now: float, expiration_ms: int | None
) -> None:
    _update(
        mailbox_email,
        "watch_last_attempt_unix = %s, watch_last_success_unix = %s, "
        "watch_expiration_ms = %s, watch_next_attempt_unix = NULL, "
        "watch_last_error = NULL",
        (now, now, expiration_ms),
    )


def record_watch_failure(
    mailbox_email: str, now: float, error: str, retry_after_seconds: float = 300
) -> None:
    _update(
        mailbox_email,
        "watch_last_attempt_unix = %s, watch_next_attempt_unix = %s, "
        "watch_last_error = %s",
        (now, now + retry_after_seconds, error),
    )


def record_sync_attempt(mailbox_email: str, now: float) -> None:
    _update(mailbox_email, "sync_last_attempt_unix = %s", (now,))


def record_sync_success(mailbox_email: str, now: float) -> None:
    _update(
        mailbox_email,
        "sync_last_attempt_unix = %s, sync_last_success_unix = %s, "
        "sync_last_error = NULL",
        (now, now),
    )


def record_sync_failure(mailbox_email: str, now: float, error: str) -> None:
    _update(
        mailbox_email,
        "sync_last_attempt_unix = %s, sync_last_error = %s",
        (now, error),
    )


def acquire_sync_lease(
    mailbox_email: str, owner: str, now: float, lease_seconds: float = 600
) -> bool:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_mailbox_state
            SET lease_owner = %s, lease_expires_unix = %s
            WHERE mailbox_email = %s
              AND (lease_expires_unix IS NULL OR lease_expires_unix < %s
                   OR lease_owner = %s)
            """,
            (owner, now + lease_seconds, mailbox_email, now, owner),
        )
        acquired = cur.rowcount == 1
        conn.commit()
    return acquired


def release_sync_lease(mailbox_email: str, owner: str) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_mailbox_state
            SET lease_owner = NULL, lease_expires_unix = NULL
            WHERE mailbox_email = %s AND lease_owner = %s
            """,
            (mailbox_email, owner),
        )
        conn.commit()


def _update(mailbox_email: str, assignment: str, values: tuple) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE gmail_mailbox_state SET {assignment} WHERE mailbox_email = %s",
            (*values, mailbox_email),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise RuntimeError(f"Gmail mailbox state is missing for {mailbox_email}")
        conn.commit()
