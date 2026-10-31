"""Recover from an expired Gmail history cursor without silently skipping mail.

Gmail only keeps history for a limited time. When ``history.list`` rejects the
stored ``startHistoryId`` with 404, we:

1. read the mailbox's *current* historyId (taken first, so anything arriving
   during the gap fill is newer than the new cursor and is caught by the next
   normal sync),
2. re-scan the gap with a time-bounded ``messages.list`` search through the
   same idempotent ingest path, and
3. compare-and-set the cursor forward and record what happened.
"""

from __future__ import annotations

import logging
from typing import Any

from src.channels.email.config import EmailConfig
from src.channels.email.message_ingest import IngestRun
from src.channels.email.state import (
    GmailMailboxState,
    advance_cursor,
    record_cursor_reset,
)

logger = logging.getLogger(__name__)

GAP_MARGIN_SECONDS = 24 * 60 * 60
MAX_LOOKBACK_SECONDS = 30 * 24 * 60 * 60
DEFAULT_LOOKBACK_SECONDS = 7 * 24 * 60 * 60
MAX_GAP_MESSAGES = 5000


def recovery_window_start(state: GmailMailboxState, now: float) -> float:
    anchor = next(
        (
            value
            for value in (
                state.sync_last_success_unix,
                state.watch_last_success_unix,
                state.initialization_started_unix,
            )
            if value is not None
        ),
        None,
    )
    if anchor is None:
        return now - DEFAULT_LOOKBACK_SECONDS
    return max(anchor - GAP_MARGIN_SECONDS, now - MAX_LOOKBACK_SECONDS)


def recover_expired_cursor(
    gmail: Any,
    config: EmailConfig,
    state: GmailMailboxState,
    expected_cursor: str,
    run: IngestRun,
    now: float,
    *,
    max_messages: int = MAX_GAP_MESSAGES,
) -> dict:
    """Gap-fill and move the cursor to the mailbox's current historyId."""
    profile = gmail.users().getProfile(userId="me").execute()
    fresh_history_id = str(profile["historyId"])
    window_start = recovery_window_start(state, now)
    query = f"after:{int(window_start)}"

    scanned = 0
    capped = False
    page_token: str | None = None
    while not capped:
        response = (
            gmail.users()
            .messages()
            .list(userId="me", q=query, maxResults=500, pageToken=page_token)
            .execute()
        )
        for item in response.get("messages") or []:
            if scanned >= max_messages:
                capped = True
                break
            scanned += 1
            run.ingest(str(item["id"]))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
        run.renew_lease()

    if fresh_history_id != expected_cursor:
        advance_cursor(config.mailbox_email, expected_cursor, fresh_history_id)
    detail = {
        "reason": "history.list 404 (startHistoryId expired)",
        "from_history_id": expected_cursor,
        "to_history_id": fresh_history_id,
        "window_start_unix": int(window_start),
        "query": query,
        "messages_scanned": scanned,
        "skipped_not_found": run.skipped_not_found,
        "capped": capped,
        "max_messages": max_messages,
    }
    record_cursor_reset(config.mailbox_email, now, detail)
    log = logger.error if capped else logger.warning
    log(
        "Gmail history cursor recovered%s: mailbox=%s detail=%s",
        (
            " (GAP SCAN HIT CAP - older mail in the window was not scanned)"
            if capped
            else ""
        ),
        config.mailbox_email,
        detail,
    )
    return detail
