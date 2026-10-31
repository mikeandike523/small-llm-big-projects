"""Incremental Gmail history processing."""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from src.channels.email.config import EmailConfig
from src.channels.email.google_errors import (
    google_error_text,
    is_google_not_found,
    log_google_error,
)
from src.channels.email.message_ingest import IngestRun
from src.channels.email.notification_store import (
    claim_pending_batch,
    mark_batch_processed,
    record_batch_error,
)
from src.channels.email.recovery import recover_expired_cursor
from src.channels.email.state import (
    SyncLeaseLostError,
    acquire_sync_lease,
    advance_cursor,
    load_mailbox_state,
    record_sync_attempt,
    record_sync_failure,
    record_sync_success,
    release_sync_lease,
)

logger = logging.getLogger(__name__)


class HistoryCursorExpiredError(RuntimeError):
    """history.list rejected the stored startHistoryId with 404."""


def _message_ids(history: list[dict]) -> list[str]:
    ordered: dict[str, None] = {}
    for entry in history:
        for addition in entry.get("messagesAdded") or []:
            message_id = str((addition.get("message") or {}).get("id") or "")
            if message_id:
                ordered[message_id] = None
    return list(ordered)


def _list_history_page(gmail: Any, cursor: str, page_token: str | None) -> dict:
    try:
        return (
            gmail.users()
            .history()
            .list(
                userId="me",
                startHistoryId=cursor,
                historyTypes=["messageAdded"],
                pageToken=page_token,
                maxResults=500,
            )
            .execute()
        )
    except Exception as exc:
        if is_google_not_found(exc):
            raise HistoryCursorExpiredError(google_error_text(exc)) from exc
        raise


def _sync_history(gmail: Any, cursor: str, run: IngestRun) -> str:
    """Ingest every message added after ``cursor``; return the new historyId."""
    page_token: str | None = None
    latest_history_id = cursor
    while True:
        response = _list_history_page(gmail, cursor, page_token)
        latest_history_id = str(response.get("historyId") or latest_history_id)
        for message_id in _message_ids(response.get("history") or []):
            run.ingest(message_id)
        page_token = response.get("nextPageToken")
        if not page_token:
            return latest_history_id
        run.renew_lease()


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
        run = IngestRun(gmail, config, owner)
        recovered = False
        try:
            latest_history_id = _sync_history(gmail, cursor, run)
        except HistoryCursorExpiredError as exc:
            logger.warning(
                "Gmail history cursor expired; starting gap recovery: "
                "mailbox=%s cursor=%s error=%s",
                config.mailbox_email,
                cursor,
                exc,
            )
            detail = recover_expired_cursor(
                gmail, config, state, cursor, run, attempt_time
            )
            latest_history_id = detail["to_history_id"]
            recovered = True
        else:
            if latest_history_id != cursor:
                advance_cursor(config.mailbox_email, cursor, latest_history_id)

        mark_batch_processed(config.mailbox_email, batch_id)
        record_sync_success(config.mailbox_email, attempt_time)
        logger.info(
            "Gmail history sync succeeded: mailbox=%s from_history_id=%s "
            "to_history_id=%s message_count=%d skipped_not_found=%d recovered=%s",
            config.mailbox_email,
            cursor,
            latest_history_id,
            len(run.processed_ids),
            run.skipped_not_found,
            recovered,
        )
        return True
    except SyncLeaseLostError:
        # Another worker now owns this range; it will advance the cursor and
        # mark the notifications it claimed. The cursor was not moved here.
        logger.warning(
            "Gmail sync abandoned after losing its lease: mailbox=%s",
            config.mailbox_email,
        )
        return False
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
