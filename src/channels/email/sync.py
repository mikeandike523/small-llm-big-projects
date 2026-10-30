"""Incremental Gmail history processing."""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from src.channels.email.config import EmailConfig
from src.channels.email.debug_store import is_debug_thread_known, upsert_debug_message
from src.channels.email.filtering import classify_alias_message
from src.channels.email.google_errors import google_error_text, log_google_error
from src.channels.email.mime import parse_gmail_message
from src.channels.email.notification_store import (
    claim_pending_batch,
    mark_batch_processed,
    record_batch_error,
)
from src.channels.email.session_integration import handle_inbound_email_stub
from src.channels.email.state import (
    acquire_sync_lease,
    advance_cursor,
    load_mailbox_state,
    record_sync_attempt,
    record_sync_failure,
    record_sync_success,
    release_sync_lease,
)

logger = logging.getLogger(__name__)


def _message_ids(history: list[dict]) -> list[str]:
    ordered: dict[str, None] = {}
    for entry in history:
        for addition in entry.get("messagesAdded") or []:
            message_id = str((addition.get("message") or {}).get("id") or "")
            if message_id:
                ordered[message_id] = None
    return list(ordered)


def _get_message(gmail: Any, message_id: str) -> dict:
    return (
        gmail.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )


def _store_relevant_thread(gmail: Any, config: EmailConfig, message: dict) -> None:
    parsed = classify_alias_message(parse_gmail_message(message), config.alias_email)
    if not parsed.relevant_to_alias and not is_debug_thread_known(
        parsed.gmail_thread_id
    ):
        return

    thread = (
        gmail.users()
        .threads()
        .get(userId="me", id=parsed.gmail_thread_id, format="full")
        .execute()
    )
    for raw_message in thread.get("messages") or []:
        thread_message = classify_alias_message(
            parse_gmail_message(raw_message), config.alias_email
        )
        upsert_debug_message(thread_message)

    # Deliberately has no side effects today. This is the extension point for
    # creating a session or forwarding mail into an existing session.
    if parsed.relevant_to_alias:
        handle_inbound_email_stub(parsed)


def synchronize_mailbox(
    gmail: Any,
    config: EmailConfig,
    *,
    now: float | None = None,
) -> bool:
    """Process all history after the durable cursor; return false if leased."""
    attempt_time = time.time() if now is None else now
    owner = f"email-sync-{uuid4()}"
    batch_id = f"notification-batch-{uuid4()}"
    if not acquire_sync_lease(config.mailbox_email, owner, attempt_time):
        logger.info("Gmail sync skipped because another worker owns the lease")
        return False

    try:
        state = load_mailbox_state(config.mailbox_email)
        cursor = state.last_processed_history_id
        if cursor is None:
            logger.info("Gmail sync deferred until watch initializes its cursor")
            return True

        record_sync_attempt(config.mailbox_email, attempt_time)
        claim_pending_batch(config.mailbox_email, batch_id)
        page_token: str | None = None
        latest_history_id = cursor
        processed_ids: set[str] = set()
        while True:
            request = (
                gmail.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=cursor,
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                    maxResults=500,
                )
            )
            response = request.execute()
            latest_history_id = str(response.get("historyId") or latest_history_id)
            for message_id in _message_ids(response.get("history") or []):
                if message_id in processed_ids:
                    continue
                processed_ids.add(message_id)
                _store_relevant_thread(gmail, config, _get_message(gmail, message_id))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        if latest_history_id != cursor:
            advance_cursor(config.mailbox_email, cursor, latest_history_id)
        mark_batch_processed(config.mailbox_email, batch_id)
        record_sync_success(config.mailbox_email, attempt_time)
        logger.info(
            "Gmail history sync succeeded: mailbox=%s from_history_id=%s "
            "to_history_id=%s message_count=%d",
            config.mailbox_email,
            cursor,
            latest_history_id,
            len(processed_ids),
        )
        return True
    except Exception as exc:
        error = google_error_text(exc)
        record_batch_error(config.mailbox_email, batch_id, error)
        record_sync_failure(config.mailbox_email, attempt_time, error)
        log_google_error(
            "gmail.users.history.list/message/thread processing",
            exc,
            mailbox=config.mailbox_email,
            context={"cursor_is_preserved": True},
        )
        raise
    finally:
        release_sync_lease(config.mailbox_email, owner)
