"""Turns <-> chat history cache rows (migration v18).

`chat_turn_index` and `chat_history_cache` hold the small pieces of a session
that are read often: turn boundaries and titles, and per subturn the fields a
closed subturn contributes to later LLM requests. This module is the only place
that maps between those rows and the session model, so the live save path and
the `fill-session-cache` backfill always produce identical rows.

A turn rebuilt from cache rows is a *stub*: each subturn keeps its user text,
summary and flags, and its exchanges are reduced to one final exchange holding
the final answer. That is exactly what every reader of sealed turns uses
(`_build_llm_payload`, the continuation detector, skill selector and title
context), so they need no changes.
"""

from __future__ import annotations

from src.utils.session_model import (
    SUBTURN_ORIGIN_USER,
    LLMExchange,
    Subturn,
    Turn,
)


def subturn_final_response(subturn: Subturn) -> str:
    """The subturn's final answer: its last final exchange, else its last one."""
    for ex in reversed(subturn.exchanges):
        if ex.is_final:
            return ex.assistant_content
    if subturn.exchanges:
        return subturn.exchanges[-1].assistant_content
    return ""


def project_turn_row(turn: Turn, turn_seq: int, start_event_id: int | None) -> dict:
    """The chat_turn_index row for a turn (`start_event_id` None = unknown)."""
    return {
        "turn_seq": turn_seq,
        "turn_id": turn.id,
        "start_event_id": start_event_id,
        "title": turn.task_title,
        "completed": bool(turn.completed),
    }


def project_subturn_row(turn_seq: int, subturn_seq: int, subturn: Subturn) -> dict:
    """The chat_history_cache row for one subturn (`subturn_seq` is 1-based)."""
    return {
        "turn_seq": turn_seq,
        "subturn_seq": subturn_seq,
        "subturn_id": subturn.id,
        "user_text": subturn.user_text,
        "user_text_with_context": subturn.user_text_with_context,
        "final_response": subturn_final_response(subturn),
        "detailed_summary": subturn.detailed_summary,
        "is_continuation": bool(subturn.is_continuation),
        "approval_mode": subturn.approval_mode,
        "origin": subturn.origin or SUBTURN_ORIGIN_USER,
    }


def project_turn(
    turn: Turn, turn_seq: int, start_event_id: int | None
) -> tuple[dict, list[dict]]:
    """The index row and every cache row for one turn."""
    return project_turn_row(turn, turn_seq, start_event_id), [
        project_subturn_row(turn_seq, i, st) for i, st in enumerate(turn.subturns, 1)
    ]


def stub_turn_from_cache(turn_row: dict, subturn_rows: list[dict]) -> Turn:
    """Rebuild a sealed turn from its rows (subturn_rows in subturn_seq order)."""
    subturns = [
        Subturn(
            id=row["subturn_id"],
            user_text=row.get("user_text") or "",
            user_text_with_context=row.get("user_text_with_context") or "",
            exchanges=[
                LLMExchange(
                    assistant_content=row.get("final_response") or "",
                    is_final=True,
                )
            ],
            is_continuation=bool(row.get("is_continuation")),
            detailed_summary=row.get("detailed_summary"),
            approval_mode=row.get("approval_mode"),
            origin=row.get("origin") or SUBTURN_ORIGIN_USER,
        )
        for row in subturn_rows
    ]
    return Turn(
        id=turn_row["turn_id"],
        subturns=subturns,
        completed=bool(turn_row.get("completed")),
        task_title=turn_row.get("title"),
        from_cache=True,
    )
