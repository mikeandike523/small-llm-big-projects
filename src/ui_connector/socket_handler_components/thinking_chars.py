"""Per-subturn thinking character counting (display metadata, migration v17).

Thinking text is never persisted, so the UI's "thinking chars" pill is backed
by a count of streamed thinking characters: native reasoning plus content
streamed as IRAT thinking. The stored total may lag the live stream.

Counts are added to MySQL every `FLUSH_EVERY` streamed chunks and once when
the LLM exchange ends, inline in the streaming callback (no extra thread). A
failed write is logged and its counts are dropped; it never interrupts the
stream.
"""

from __future__ import annotations

import logging

from src.utils.sql.session_store_db import add_thinking_chars

logger = logging.getLogger(__name__)

FLUSH_EVERY = 10


class ThinkingCharCounter:
    def __init__(self, session_id: str, subturn_id: str) -> None:
        self._session_id = session_id
        self._subturn_id = subturn_id
        self._native = 0
        self._irat = 0
        self._chunks = 0  # chunks added since the last write

    def add_native(self, chars: int) -> None:
        self._native += chars
        self._maybe_flush()

    def add_irat(self, chars: int) -> None:
        self._irat += chars
        self._maybe_flush()

    def flush(self) -> None:
        """Write the not-yet-saved counts (call once at the end of the exchange)."""
        native, irat = self._native, self._irat
        self._chunks = 0
        if not native and not irat:
            return
        self._native = self._irat = 0
        try:
            add_thinking_chars(self._session_id, self._subturn_id, native, irat)
        except Exception as exc:
            logger.warning(
                "Could not save thinking char counts for subturn %s: %s",
                self._subturn_id,
                exc,
            )

    def _maybe_flush(self) -> None:
        self._chunks += 1
        if self._chunks >= FLUSH_EVERY:
            self.flush()
