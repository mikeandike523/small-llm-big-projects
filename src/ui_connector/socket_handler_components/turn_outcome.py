"""How an admitted message ended, for callers that run turns headlessly.

``new_user_message(..., on_finished=cb)`` calls ``cb(TurnOutcome)`` after the
turn reservation is released (so the session is already free again).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.utils.conversation_history import final_answer
from src.utils.session_model import Subturn, Turn

logger = logging.getLogger(__name__)

NO_FINAL_ANSWER_ERROR = (
    "the agent stopped without a final answer (see the session UI for details)"
)


@dataclass(frozen=True)
class TurnOutcome:
    """Exactly one of: an answer, a cancellation, or an error message."""

    final_text: str | None = None
    cancelled: bool = False
    error: str | None = None

    @classmethod
    def failed(cls, error: str) -> "TurnOutcome":
        return cls(error=error or NO_FINAL_ANSWER_ERROR)


def outcome_from_turn(turn: Turn, subturn: Subturn) -> TurnOutcome:
    if turn.was_cancelled:
        return TurnOutcome(cancelled=True)
    answer = final_answer(subturn)
    if answer is None or not answer.strip():
        return TurnOutcome.failed(NO_FINAL_ANSWER_ERROR)
    return TurnOutcome(final_text=answer)


def deliver_outcome(
    on_finished: Callable[[TurnOutcome], None] | None,
    outcome: TurnOutcome | None,
    *,
    session_id: str,
) -> None:
    """Call the callback; its failures are logged, never raised into the turn."""
    if on_finished is None:
        return
    try:
        on_finished(outcome or TurnOutcome.failed(NO_FINAL_ANSWER_ERROR))
    except Exception:
        logger.exception("Turn on_finished callback failed: session_id=%s", session_id)
