"""Past turns as conversation: the one place that turns them into history.

Stored history is never repaired. A turn the server stopped in the middle of
stays exactly as it was written: an open turn, perhaps a tool call without a
result, no final answer. Every reader that rebuilds the earlier conversation
(the LLM payload, the continuation detector, the skill selector, the title
context) goes through this module, which fills those gaps with explicit text
when the conversation is built:

  no user text and no answer         the subturn is skipped
  no final exchange                  INTERRUPTED_ANSWER
  a final exchange with empty text   NO_RESPONSE
  an answer but no user text         NO_USER_MESSAGE (keeps roles alternating)
  a tool call without a result       INTERRUPTED_TOOL_RESULT (LLMExchange)

It works the same on full replays and on turns rebuilt from the chat history
cache (a cached subturn without a final answer has no exchanges).

Markers the agent loop writes as real outcomes (`[Action Cancelled by User]`,
error markers) are final exchanges like any answer and pass through unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.session_model import (
    INTERRUPTED_TOOL_RESULT,
    Session,
    Subturn,
    Turn,
)

INTERRUPTED_ANSWER = "[Interrupted: this request ended before an answer was given]"
NO_RESPONSE = "[No response]"
NO_USER_MESSAGE = "[No user message was recorded]"

__all__ = [
    "INTERRUPTED_ANSWER",
    "INTERRUPTED_TOOL_RESULT",
    "NO_RESPONSE",
    "NO_USER_MESSAGE",
    "ClosedSubturn",
    "assistant_context",
    "closed_history",
    "closed_subturn",
    "final_answer",
]


@dataclass(frozen=True)
class ClosedSubturn:
    """One closed subturn, normalized: every text field is non-empty."""

    turn_id: str
    subturn_id: str
    user_text: str
    user_context: str  # the user message as the LLM saw it (with context)
    answer: str
    notes: str | None  # Context Notes (detailed_summary)
    origin: str
    interrupted: bool


def final_answer(subturn: Subturn) -> str | None:
    """The content of the subturn's last final exchange; None if it has none."""
    for ex in reversed(subturn.exchanges):
        if ex.is_final:
            return ex.assistant_content or ""
    return None


def closed_subturn(turn: Turn, subturn: Subturn) -> ClosedSubturn | None:
    """Normalize one closed subturn; None if nothing about it was recorded."""
    user_text = subturn.user_text or ""
    user_context = subturn.user_text_with_context or user_text
    answer = final_answer(subturn)
    if not user_context.strip():
        if not (answer or "").strip():
            return None
        user_text = user_context = NO_USER_MESSAGE
    elif not user_text.strip():
        user_text = user_context
    if answer is None:
        text, interrupted = INTERRUPTED_ANSWER, True
    else:
        text, interrupted = (answer if answer.strip() else NO_RESPONSE), False
    return ClosedSubturn(
        turn_id=turn.id,
        subturn_id=subturn.id,
        user_text=user_text,
        user_context=user_context,
        answer=text,
        notes=subturn.detailed_summary or None,
        origin=subturn.origin,
        interrupted=interrupted,
    )


def closed_history(
    session: Session, current_turn: Turn | None = None
) -> list[ClosedSubturn]:
    """Every closed subturn before the live one, normalized, in order.

    That is every subturn of `session.completed_turns`, then the earlier
    subturns of `current_turn` (its last subturn is the live one).
    """
    pairs = [(t, st) for t in session.completed_turns for st in t.subturns]
    if current_turn is not None:
        pairs.extend((current_turn, st) for st in current_turn.subturns[:-1])
    history = []
    for turn, st in pairs:
        cs = closed_subturn(turn, st)
        if cs is not None:
            history.append(cs)
    return history


def assistant_context(cs: ClosedSubturn) -> str:
    """The assistant message a closed subturn contributes to later requests:

      {answer}

      Context Notes:
      {notes}

    (just the answer when there are no notes).
    """
    if cs.notes:
        return f"{cs.answer}\n\nContext Notes:\n{cs.notes}"
    return cs.answer
