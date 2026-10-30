"""Gmail watch registration and renewal."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.channels.email.config import EmailConfig
from src.channels.email.google_errors import google_error_text, log_google_error
from src.channels.email.state import (
    initialize_cursor_if_absent,
    mark_initialization_started,
    record_watch_attempt,
    record_watch_failure,
    record_watch_success,
)

logger = logging.getLogger(__name__)


def register_or_renew_watch(
    gmail: Any,
    config: EmailConfig,
    *,
    now: float | None = None,
) -> dict:
    """Register Gmail push and initialize a new mailbox cursor exactly once."""
    attempt_time = time.time() if now is None else now
    mark_initialization_started(config.mailbox_email, attempt_time)
    record_watch_attempt(config.mailbox_email, attempt_time)
    try:
        response = (
            gmail.users()
            .watch(
                userId="me",
                body={"topicName": config.topic_resource},
            )
            .execute()
        )
        history_id = str(response["historyId"])
        expiration_ms = (
            int(response["expiration"]) if response.get("expiration") else None
        )
        initialized = initialize_cursor_if_absent(config.mailbox_email, history_id)
        record_watch_success(config.mailbox_email, attempt_time, expiration_ms)
        logger.info(
            "Gmail watch registration succeeded: mailbox=%s history_id=%s "
            "expiration_ms=%s initialized_cursor=%s",
            config.mailbox_email,
            history_id,
            expiration_ms,
            initialized,
        )
        return response
    except Exception as exc:
        error = google_error_text(exc)
        record_watch_failure(config.mailbox_email, attempt_time, error)
        log_google_error(
            "gmail.users.watch",
            exc,
            mailbox=config.mailbox_email,
            context={"topic_resource": config.topic_resource},
        )
        raise
