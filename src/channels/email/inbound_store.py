"""MySQL-backed per-session email queue (`email_inbound`, migration v23).

Each row is one inbound email for one session. It is the queue item, the
de-duplication record (UNIQUE session_id + gmail_message_id) and the anchor
that every reply about that email is threaded against.

Status flow::

    queued -> running -> done | failed | cancelled
    queued -> discarded            (alias changed / email disabled; no reply)

``final_reply_sent_at`` guards the one end-of-turn reply (answer, error or
cancellation notice); a row in done/failed/cancelled without it still owes a
reply, so a failed send is retried by the runner's next pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.data import get_pool

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_DISCARDED = "discarded"

FINISHED_STATUSES = (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED)

REPLY_QUEUED = "queued_reply_sent_at"
REPLY_WORKING = "working_reply_sent_at"
REPLY_FINAL = "final_reply_sent_at"
_REPLY_COLUMNS = (REPLY_QUEUED, REPLY_WORKING, REPLY_FINAL)


@dataclass(frozen=True)
class NewInboundEmail:
    session_id: str
    gmail_message_id: str
    gmail_thread_id: str
    alias: str
    sender_address: str
    subject: str
    message_id_header: str
    references_header: str
    body_text: str
    received_at: float


@dataclass(frozen=True)
class InboundEmail:
    id: int
    session_id: str
    gmail_message_id: str
    gmail_thread_id: str
    alias: str
    sender_address: str
    subject: str
    message_id_header: str
    references_header: str
    body_text: str
    received_at: float
    status: str
    needs_queued_reply: bool
    queued_reply_sent_at: float | None
    working_reply_sent_at: float | None
    final_reply_sent_at: float | None
    final_text: str | None
    error_detail: str | None


_SELECT_COLS = (
    "id, session_id, gmail_message_id, gmail_thread_id, alias, sender_address, "
    "subject, message_id_header, references_header, body_text, received_at, "
    "status, needs_queued_reply, queued_reply_sent_at, working_reply_sent_at, "
    "final_reply_sent_at, final_text, error_detail"
)


def _row(row: dict) -> InboundEmail:
    def _opt_float(name: str) -> float | None:
        value = row.get(name)
        return float(value) if value is not None else None

    return InboundEmail(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        gmail_message_id=str(row["gmail_message_id"]),
        gmail_thread_id=str(row["gmail_thread_id"]),
        alias=str(row["alias"]),
        sender_address=str(row["sender_address"]),
        subject=str(row.get("subject") or ""),
        message_id_header=str(row.get("message_id_header") or ""),
        references_header=str(row.get("references_header") or ""),
        body_text=str(row.get("body_text") or ""),
        received_at=float(row["received_at"]),
        status=str(row["status"]),
        needs_queued_reply=bool(row.get("needs_queued_reply")),
        queued_reply_sent_at=_opt_float("queued_reply_sent_at"),
        working_reply_sent_at=_opt_float("working_reply_sent_at"),
        final_reply_sent_at=_opt_float("final_reply_sent_at"),
        final_text=row.get("final_text"),
        error_detail=row.get("error_detail"),
    )


def _select(where: str, params: tuple, *, order: str = "received_at ASC, id ASC"):
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"SELECT {_SELECT_COLS} FROM email_inbound WHERE {where} ORDER BY {order}",
            params,
        )
        return [_row(row) for row in cur.fetchall()]


def _execute(sql: str, params: tuple) -> int:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        changed = cur.rowcount
        conn.commit()
    return changed


def insert_inbound(item: NewInboundEmail, *, needs_queued_reply: bool) -> bool:
    """Queue one email; False when this (session, message) was already seen."""
    return (
        _execute(
            """
            INSERT IGNORE INTO email_inbound
                (session_id, gmail_message_id, gmail_thread_id, alias,
                 sender_address, subject, message_id_header, references_header,
                 body_text, received_at, needs_queued_reply)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item.session_id,
                item.gmail_message_id,
                item.gmail_thread_id,
                item.alias,
                item.sender_address,
                item.subject,
                item.message_id_header,
                item.references_header,
                item.body_text,
                item.received_at,
                1 if needs_queued_reply else 0,
            ),
        )
        == 1
    )


def has_unfinished_work(session_id: str) -> bool:
    """True while any queued or running email exists for the session."""
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM email_inbound WHERE session_id = %s "
            "AND status IN (%s, %s) LIMIT 1",
            (session_id, STATUS_QUEUED, STATUS_RUNNING),
        )
        return cur.fetchone() is not None


def sessions_with_pending_work() -> list[str]:
    """Sessions with queued mail or an end-of-turn reply still owed."""
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT session_id FROM email_inbound
            WHERE status = %s
               OR (status IN ({", ".join(["%s"] * len(FINISHED_STATUSES))})
                   AND final_reply_sent_at IS NULL)
            """,
            (STATUS_QUEUED, *FINISHED_STATUSES),
        )
        return [str(row[0]) for row in cur.fetchall()]


def queued_needing_queued_reply(session_id: str) -> list[InboundEmail]:
    return _select(
        "session_id = %s AND status = %s AND needs_queued_reply = 1 "
        "AND queued_reply_sent_at IS NULL",
        (session_id, STATUS_QUEUED),
    )


def finished_needing_final_reply(session_id: str) -> list[InboundEmail]:
    placeholders = ", ".join(["%s"] * len(FINISHED_STATUSES))
    return _select(
        f"session_id = %s AND status IN ({placeholders}) "
        "AND final_reply_sent_at IS NULL",
        (session_id, *FINISHED_STATUSES),
    )


def oldest_queued(session_id: str) -> InboundEmail | None:
    rows = _select("session_id = %s AND status = %s", (session_id, STATUS_QUEUED))
    return rows[0] if rows else None


def try_mark_running(inbound_id: int) -> bool:
    """Compare-and-set queued -> running; False if someone else moved it."""
    return (
        _execute(
            "UPDATE email_inbound SET status = %s WHERE id = %s AND status = %s",
            (STATUS_RUNNING, inbound_id, STATUS_QUEUED),
        )
        == 1
    )


def requeue(inbound_id: int) -> None:
    _execute(
        "UPDATE email_inbound SET status = %s WHERE id = %s AND status = %s",
        (STATUS_QUEUED, inbound_id, STATUS_RUNNING),
    )


def mark_finished(
    inbound_id: int,
    status: str,
    *,
    final_text: str | None = None,
    error_detail: str | None = None,
) -> None:
    if status not in FINISHED_STATUSES:
        raise ValueError(f"not a finished status: {status}")
    _execute(
        "UPDATE email_inbound SET status = %s, final_text = %s, error_detail = %s "
        "WHERE id = %s AND status = %s",
        (status, final_text, error_detail, inbound_id, STATUS_RUNNING),
    )


def mark_reply_sent(inbound_id: int, column: str, sent_at: float) -> None:
    if column not in _REPLY_COLUMNS:
        raise ValueError(f"unknown reply column: {column}")
    _execute(
        f"UPDATE email_inbound SET {column} = %s WHERE id = %s",
        (sent_at, inbound_id),
    )


def discard_queued(session_id: str) -> int:
    """Drop queued (not yet started) mail after an alias change or disable."""
    return _execute(
        "UPDATE email_inbound SET status = %s WHERE session_id = %s AND status = %s",
        (STATUS_DISCARDED, session_id, STATUS_QUEUED),
    )


def fail_orphaned_running(error_detail: str) -> int:
    """At startup no email turn can be running; such rows died with the server."""
    return _execute(
        "UPDATE email_inbound SET status = %s, error_detail = %s WHERE status = %s",
        (STATUS_FAILED, error_detail, STATUS_RUNNING),
    )


def sent_final_texts(session_id: str, gmail_thread_id: str) -> list[str]:
    """Answers this session already emailed in a thread (for quote stripping)."""
    rows = _select(
        "session_id = %s AND gmail_thread_id = %s AND status = %s "
        "AND final_reply_sent_at IS NOT NULL AND final_text IS NOT NULL",
        (session_id, gmail_thread_id, STATUS_DONE),
        order="received_at DESC, id DESC",
    )
    return [row.final_text for row in rows if row.final_text]
