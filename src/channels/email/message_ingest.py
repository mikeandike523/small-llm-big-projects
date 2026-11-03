"""Per-message Gmail ingestion shared by history sync and cursor recovery."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.channels.email.config import EmailConfig
from src.channels.email.debug_store import is_debug_thread_known, upsert_debug_message
from src.channels.email.filtering import classify_alias_message
from src.channels.email.google_errors import is_google_not_found
from src.channels.email.mime import parse_gmail_message
from src.channels.email.router import route_inbound_message
from src.channels.email.state import SyncLeaseLostError, renew_sync_lease
from src.utils.sql.email_alias_db import list_all_claimed_aliases

logger = logging.getLogger(__name__)

LEASE_RENEW_EVERY_MESSAGES = 25


class IngestRun:
    """One sync run: de-duplicates ids, skips vanished mail, keeps the lease."""

    def __init__(
        self,
        gmail: Any,
        config: EmailConfig,
        lease_owner: str,
        *,
        clock: Callable[[], float] = time.time,
        renew_every: int = LEASE_RENEW_EVERY_MESSAGES,
    ) -> None:
        self._gmail = gmail
        self._config = config
        self._lease_owner = lease_owner
        self._clock = clock
        self._renew_every = max(1, renew_every)
        self.processed_ids: set[str] = set()
        self.skipped_not_found = 0
        self._claimed_aliases: frozenset[str] | None = None

    def _aliases(self) -> frozenset[str]:
        """Claimed aliases, read once per sync run."""
        if self._claimed_aliases is None:
            self._claimed_aliases = frozenset(list_all_claimed_aliases())
        return self._claimed_aliases

    def renew_lease(self) -> None:
        if not renew_sync_lease(
            self._config.mailbox_email, self._lease_owner, self._clock()
        ):
            raise SyncLeaseLostError(
                "Gmail sync lease was taken over by another worker"
            )

    def ingest(self, message_id: str) -> None:
        if message_id in self.processed_ids:
            return
        self.processed_ids.add(message_id)
        try:
            message = (
                self._gmail.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            self._store_relevant_thread(message)
        except Exception as exc:
            if not is_google_not_found(exc):
                raise
            # Permanently deleted between listing and fetching. Retrying can
            # never succeed, so skip it instead of pinning the cursor forever.
            self.skipped_not_found += 1
            logger.warning(
                "Skipping Gmail message that no longer exists: "
                "mailbox=%s message_id=%s",
                self._config.mailbox_email,
                message_id,
            )
        if len(self.processed_ids) % self._renew_every == 0:
            self.renew_lease()

    def _store_relevant_thread(self, message: dict) -> None:
        aliases = self._aliases()
        parsed = classify_alias_message(parse_gmail_message(message), aliases)
        if not parsed.relevant_to_alias and not is_debug_thread_known(
            parsed.gmail_thread_id
        ):
            return

        thread = (
            self._gmail.users()
            .threads()
            .get(userId="me", id=parsed.gmail_thread_id, format="full")
            .execute()
        )
        for raw_message in thread.get("messages") or []:
            upsert_debug_message(
                classify_alias_message(parse_gmail_message(raw_message), aliases)
            )

        # Queue rows are de-duplicated by (session, gmail_message_id), so the
        # re-delivery caused by cursor recovery or lease takeover is harmless.
        if parsed.relevant_to_alias:
            route_inbound_message(parsed, on_queued=self._on_queued)

    @staticmethod
    def _on_queued(_session_id: str) -> None:
        from src.channels.email.email_runner import notify_email_runner

        notify_email_runner()
