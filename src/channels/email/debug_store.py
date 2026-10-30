"""Persistence and query helpers for the email debug page."""

from __future__ import annotations

import json

from src.channels.email.mime import ParsedGmailMessage
from src.data import get_pool


def is_debug_thread_known(gmail_thread_id: str) -> bool:
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM gmail_debug_messages WHERE gmail_thread_id = %s LIMIT 1",
            (gmail_thread_id,),
        )
        return cur.fetchone() is not None


def upsert_debug_message(message: ParsedGmailMessage) -> None:
    pool = get_pool()
    values = (
        message.gmail_message_id,
        message.gmail_thread_id,
        message.gmail_history_id,
        message.internal_date_ms,
        message.direction,
        message.subject_text,
        message.from_header,
        message.to_header,
        message.cc_header,
        message.delivered_to_header,
        message.original_to_header,
        message.message_id_header,
        message.in_reply_to_header,
        message.references_header,
        message.snippet,
        message.text_body,
        message.html_body,
        json.dumps(message.labels),
        json.dumps(message.attachments),
        1 if message.relevant_to_alias else 0,
        message.alias_match_reason,
    )
    with pool.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gmail_debug_messages
                (gmail_message_id, gmail_thread_id, gmail_history_id,
                 internal_date_ms, direction, subject_text, from_header,
                 to_header, cc_header, delivered_to_header, original_to_header,
                 message_id_header, in_reply_to_header, references_header,
                 snippet, text_body, html_body, labels_json, attachments_json,
                 relevant_to_alias, alias_match_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s) AS incoming
            ON DUPLICATE KEY UPDATE
                gmail_thread_id = incoming.gmail_thread_id,
                gmail_history_id = incoming.gmail_history_id,
                internal_date_ms = incoming.internal_date_ms,
                direction = incoming.direction,
                subject_text = incoming.subject_text,
                from_header = incoming.from_header,
                to_header = incoming.to_header,
                cc_header = incoming.cc_header,
                delivered_to_header = incoming.delivered_to_header,
                original_to_header = incoming.original_to_header,
                message_id_header = incoming.message_id_header,
                in_reply_to_header = incoming.in_reply_to_header,
                references_header = incoming.references_header,
                snippet = incoming.snippet,
                text_body = incoming.text_body,
                html_body = incoming.html_body,
                labels_json = incoming.labels_json,
                attachments_json = incoming.attachments_json,
                relevant_to_alias = incoming.relevant_to_alias,
                alias_match_reason = incoming.alias_match_reason
            """,
            values,
        )
        conn.commit()


def list_recent_threads(limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    pool = get_pool()
    with pool.get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT gmail_thread_id, MAX(internal_date_ms) AS latest_internal_date_ms
            FROM gmail_debug_messages
            GROUP BY gmail_thread_id
            ORDER BY latest_internal_date_ms DESC
            LIMIT %s
            """,
            (limit,),
        )
        summaries = cur.fetchall()
        if not summaries:
            return []
        thread_ids = [str(row["gmail_thread_id"]) for row in summaries]
        placeholders = ", ".join(["%s"] * len(thread_ids))
        cur.execute(
            f"""
            SELECT * FROM gmail_debug_messages
            WHERE gmail_thread_id IN ({placeholders})
            ORDER BY internal_date_ms ASC
            """,
            tuple(thread_ids),
        )
        messages = cur.fetchall()
    grouped: dict[str, list[dict]] = {thread_id: [] for thread_id in thread_ids}
    for row in messages:
        normalized = dict(row)
        normalized["labels"] = _json_value(normalized.pop("labels_json"))
        normalized["attachments"] = _json_value(normalized.pop("attachments_json"))
        normalized["relevant_to_alias"] = bool(normalized["relevant_to_alias"])
        for name in ("observed_at", "updated_at"):
            value = normalized.get(name)
            normalized[name] = value.isoformat() if value is not None else None
        grouped[str(row["gmail_thread_id"])].append(normalized)
    return [
        {
            "thread_id": thread_id,
            "latest_internal_date_ms": int(summary["latest_internal_date_ms"]),
            "messages": grouped[thread_id],
            "session_integration": "not_implemented",
        }
        for thread_id, summary in zip(thread_ids, summaries, strict=True)
    ]


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value
