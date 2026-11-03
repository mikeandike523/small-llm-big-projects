"""Task-title helpers used when a turn or continuation subturn starts."""

from __future__ import annotations

import logging

from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _make_sampler_request_logger,
    _make_sampler_response_logger,
    _make_sampler_usage_tracker,
)
from src.ui_connector.socket_handler_components.session_writes import write_title
from src.ui_connector.socket_handler_components.watchdogs import _fetch_task_title
from src.utils.conversation_history import closed_subturn
from src.utils.session_model import Session, Turn

logger = logging.getLogger(__name__)


def _build_title_context(session: Session, current_turn: Turn) -> str | None:
    """Build a short prior-context string for task-title recomputation on continuation subturns."""
    parts: list[str] = []
    for t in session.completed_turns:
        if t.task_title:
            parts.append(f"Previous task: {t.task_title}")
    for st in current_turn.subturns[:-1]:
        cs = closed_subturn(current_turn, st)
        if cs is None:
            continue
        user_text = cs.user_text.strip()
        if len(user_text) > 200:
            user_text = user_text[:200] + "..."
        parts.append(f"Previous subturn request: {user_text}")
    return "\n".join(parts) if parts else None


async def _maybe_fetch_task_title(
    streaming_llm,
    text: str,
    watchdog_params: dict,
    session_id: str,
    session: Session,
    current_turn: Turn,
    turn_id: str,
    prior_context: str | None = None,
) -> None:
    """Fetch a task title and emit + save it if successful.

    The LLM fetch is best-effort (failures are logged, not fatal); saving the
    title is not, so a failed save propagates like any other save.
    """
    try:
        title = await _fetch_task_title(
            streaming_llm,
            text,
            watchdog_params,
            on_usage=_make_sampler_usage_tracker(session_id, "task_title"),
            on_request_log=_make_sampler_request_logger(session_id, "task_title"),
            on_response=_make_sampler_response_logger(session_id, "task_title"),
            prior_context=prior_context,
        )
    except Exception:
        logger.warning("Task title fetch failed for turn %s", turn_id, exc_info=True)
        return
    if title:
        current_turn.task_title = title
        _emit_and_log(session_id, "task_title", {"turn_id": turn_id, "title": title})
        write_title(session_id, session, current_turn)
