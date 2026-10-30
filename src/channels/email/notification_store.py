"""Durable Pub/Sub notification intake."""

from __future__ import annotations

from dataclasses import dataclass

from src.data import get_pool


@dataclass(frozen=True)
class GmailNotification:
    pubsub_message_id: str
    subscription_resource: str
    mailbox_email: str
    notified_history_id: str


def enqueue_notification(notification: GmailNotification) -> bool:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT IGNORE INTO gmail_pubsub_notifications
                (pubsub_message_id, subscription_resource, mailbox_email,
                 notified_history_id)
            VALUES (%s, %s, %s, %s)
            """,
            (
                notification.pubsub_message_id,
                notification.subscription_resource,
                notification.mailbox_email,
                notification.notified_history_id,
            ),
        )
        inserted = cur.rowcount == 1
        conn.commit()
    return inserted


def pending_notification_count(mailbox_email: str) -> int:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM gmail_pubsub_notifications
            WHERE mailbox_email = %s AND processing_status = 'pending'
            """,
            (mailbox_email,),
        )
        row = cur.fetchone()
    return int(row[0])


def claim_pending_batch(mailbox_email: str, batch_id: str) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_pubsub_notifications
            SET processing_attempts = processing_attempts + 1,
                processing_batch_id = %s
            WHERE mailbox_email = %s AND processing_status = 'pending'
            """,
            (batch_id, mailbox_email),
        )
        conn.commit()


def mark_batch_processed(mailbox_email: str, batch_id: str) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_pubsub_notifications
            SET processing_status = 'processed', processed_at = CURRENT_TIMESTAMP(3),
                last_error = NULL
            WHERE mailbox_email = %s AND processing_status = 'pending'
              AND processing_batch_id = %s
            """,
            (mailbox_email, batch_id),
        )
        conn.commit()


def record_batch_error(mailbox_email: str, batch_id: str, error: str) -> None:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE gmail_pubsub_notifications SET last_error = %s
            WHERE mailbox_email = %s AND processing_status = 'pending'
              AND processing_batch_id = %s
            """,
            (error, mailbox_email, batch_id),
        )
        conn.commit()
