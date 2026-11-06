"""MySQL-backed email queue (`email_inbound`, migrations v23 and v24).

Each row is one inbound email for one agent. It is the queue item, the
de-duplication record (UNIQUE agent_id + gmail_message_id, so it outlives a
deleted session) and the anchor that every reply about that email is threaded
against. The router leaves ``session_id`` empty; the runner fills it in when it
finds or spawns the conversation's session.

Status flow::

    queued -> running -> done | failed | cancelled | interrupted
    queued -> discarded            (agent disabled or unregistered, session
                                    deleted; no reply)

A ``running`` row found at startup died with the previous server process and
becomes ``interrupted``.

``final_reply_sent_at`` guards the one end-of-turn reply (answer, error,
cancellation or interruption notice); a finished row without it still owes a
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
STATUS_INTERRUPTED = "interrupted"
STATUS_DISCARDED = "discarded"

FINISHED_STATUSES = (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_INTERRUPTED,
)

REPLY_QUEUED = "queued_reply_sent_at"
REPLY_WORKING = "working_reply_sent_at"
REPLY_FINAL = "final_reply_sent_at"
REPLY_APPROVAL = "approval_notice_sent_at"
_REPLY_COLUMNS = (REPLY_QUEUED, REPLY_WORKING, REPLY_FINAL, REPLY_APPROVAL)


@dataclass(frozen=True)
class NewInboundEmail:
    agent_id: str
    gmail_message_id: str
    gmail_thread_id: str
    alias: str
    sender_address: str
    sender_display_name: str | None
    subject: str
    message_id_header: str
    references_header: str
    body_text: str
    received_at: float


@dataclass(frozen=True)
class InboundEmail:
    id: int
    agent_id: str
    session_id: str | None
    gmail_message_id: str
    gmail_thread_id: str
    alias: str
    sender_address: str
    sender_display_name: str | None
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
    approval_notice_sent_at: float | None
    final_text: str | None
    error_detail: str | None


_SELECT_COLS = (
    "id, agent_id, session_id, gmail_message_id, gmail_thread_id, alias, "
    "sender_address, sender_display_name, subject, message_id_header, "
    "references_header, body_text, received_at, status, needs_queued_reply, "
    "queued_reply_sent_at, working_reply_sent_at, final_reply_sent_at, "
    "approval_notice_sent_at, final_text, error_detail"
)


def _row(row: dict) -> InboundEmail:
    def _opt_float(name: str) -> float | None:
        value = row.get(name)
        return float(value) if value is not None else None

    return InboundEmail(
        id=int(row["id"]),
        agent_id=str(row["agent_id"]),
        session_id=str(row["session_id"]) if row.get("session_id") else None,
        gmail_message_id=str(row["gmail_message_id"]),
        gmail_thread_id=str(row["gmail_thread_id"]),
        alias=str(row["alias"]),
        sender_address=str(row["sender_address"]),
        sender_display_name=row.get("sender_display_name"),
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
        approval_notice_sent_at=_opt_float("approval_notice_sent_at"),
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
    """Queue one email; False when this (agent, message) was already seen."""
    return (
        _execute(
            """
            INSERT IGNORE INTO email_inbound
                (agent_id, gmail_message_id, gmail_thread_id, alias,
                 sender_address, sender_display_name, subject, message_id_header,
                 references_header, body_text, received_at, needs_queued_reply)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item.agent_id,
                item.gmail_message_id,
                item.gmail_thread_id,
                item.alias,
                item.sender_address,
                item.sender_display_name,
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


def conversation_has_unfinished_work(
    agent_id: str, gmail_thread_id: str, sender_address: str
) -> bool:
    """True while any queued or running email exists for the conversation."""
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM email_inbound WHERE agent_id = %s AND gmail_thread_id = %s "
            "AND sender_address = %s AND status IN (%s, %s) LIMIT 1",
            (agent_id, gmail_thread_id, sender_address, STATUS_QUEUED, STATUS_RUNNING),
        )
        return cur.fetchone() is not None


def queued_without_session() -> list[InboundEmail]:
    """Mail the runner has not yet given to a conversation's session."""
    return _select("session_id IS NULL AND status = %s", (STATUS_QUEUED,))


def assign_session(inbound_id: int, session_id: str) -> None:
    _execute(
        "UPDATE email_inbound SET session_id = %s WHERE id = %s",
        (session_id, inbound_id),
    )


def sessions_with_pending_work() -> list[str]:
    """Sessions with queued mail, or an end-of-turn reply or notice still owed."""
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT session_id FROM email_inbound
            WHERE session_id IS NOT NULL
              AND (status = %s
                   OR (status IN ({", ".join(["%s"] * len(FINISHED_STATUSES))})
                       AND final_reply_sent_at IS NULL)
                   OR (status = %s
                       AND approval_notice_requested_at IS NOT NULL
                       AND approval_notice_sent_at IS NULL))
            """,
            (STATUS_QUEUED, *FINISHED_STATUSES, STATUS_RUNNING),
        )
        return [str(row[0]) for row in cur.fetchall()]


def request_approval_notice(session_id: str, requested_at: float) -> int:
    """Ask for the awaiting-approval notice on the session's running email.

    One running row is one subturn, and this only ever sets the time once, so
    the sender gets at most one notice per subturn.
    """
    return _execute(
        "UPDATE email_inbound SET approval_notice_requested_at = %s "
        "WHERE session_id = %s AND status = %s "
        "AND approval_notice_requested_at IS NULL",
        (requested_at, session_id, STATUS_RUNNING),
    )


def running_needing_approval_notice(session_id: str) -> list[InboundEmail]:
    return _select(
        "session_id = %s AND status = %s AND approval_notice_requested_at IS NOT NULL "
        "AND approval_notice_sent_at IS NULL",
        (session_id, STATUS_RUNNING),
    )


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


def discard_queued_for_agent(agent_id: str) -> int:
    """Drop not-yet-started mail after the agent is disabled or unregistered."""
    return _execute(
        "UPDATE email_inbound SET status = %s WHERE agent_id = %s AND status = %s",
        (STATUS_DISCARDED, agent_id, STATUS_QUEUED),
    )


def discard_queued_for_session(session_id: str) -> int:
    """Drop a session's queued mail before it is deleted, or it would respawn."""
    return _execute(
        "UPDATE email_inbound SET status = %s WHERE session_id = %s AND status = %s",
        (STATUS_DISCARDED, session_id, STATUS_QUEUED),
    )


def mark_orphaned_interrupted() -> int:
    """At startup no email turn can be running; such rows died with the server."""
    return _execute(
        "UPDATE email_inbound SET status = %s WHERE status = %s",
        (STATUS_INTERRUPTED, STATUS_RUNNING),
    )


def sent_final_texts(
    agent_id: str, gmail_thread_id: str, sender_address: str
) -> list[str]:
    """Answers already emailed to this person in a thread (for quote stripping).

    Answers to others in the thread stay in the body: a person joining a thread
    gets a new session, and what they quote is all it knows of the thread.
    """
    rows = _select(
        "agent_id = %s AND gmail_thread_id = %s AND sender_address = %s "
        "AND status = %s AND final_reply_sent_at IS NOT NULL "
        "AND final_text IS NOT NULL",
        (agent_id, gmail_thread_id, sender_address, STATUS_DONE),
        order="received_at DESC, id DESC",
    )
    return [row.final_text for row in rows if row.final_text]
