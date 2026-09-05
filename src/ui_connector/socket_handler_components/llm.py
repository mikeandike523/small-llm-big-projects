from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
    _emit_content_snapshot,
)
from src.ui_connector.socket_handler_components.session_store import (
    _get_session_system_prompt,
)
from src.tools import ALL_TOOL_DEFINITIONS
from src.utils.llm.streaming import StreamingLLM
from src.utils.session_model import Session, Turn, Subturn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message sanitization
# ---------------------------------------------------------------------------


def sanitize_messages_for_llm(messages: list[dict]) -> list[dict]:
    """Return a new list with all non-OpenAI-spec keys removed from every message."""
    return [
        {k: v for k, v in msg.items() if k in _state._OPENAI_MESSAGE_KEYS}
        for msg in messages
    ]


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------


def _subturn_final_response(subturn: Subturn) -> str:
    """Extract the final response text from a subturn's exchanges."""
    for ex in reversed(subturn.exchanges):
        if ex.is_final:
            return ex.assistant_content
    if subturn.exchanges:
        return subturn.exchanges[-1].assistant_content
    return ""


def _subturn_assistant_context(subturn: Subturn) -> str:
    """Return the context string for a completed subturn injected into future LLM payloads.

    When a context annotation exists (tool calls were made), reconstructs:
      {final response}

      Context Notes:
      {annotation}

    Otherwise returns just the final response.
    """
    final_response = _subturn_final_response(subturn)
    if subturn.detailed_summary:
        return f"{final_response}\n\nContext Notes:\n{subturn.detailed_summary}"
    return final_response


def _build_llm_payload(
    session: Session,
    current_turn: Turn,
    skills_section: str | None = None,
) -> list[dict]:
    """Assemble the message list actually sent to the LLM endpoint."""
    system_content = _get_session_system_prompt(session.session_id)
    if skills_section:
        system_content = system_content + "\n" + skills_section
    messages: list[dict] = [{"role": "system", "content": system_content}]

    for turn in session.completed_turns:
        for subturn in turn.subturns:
            messages.append({"role": "user", "content": subturn.user_text_with_context})
            messages.append(
                {"role": "assistant", "content": _subturn_assistant_context(subturn)}
            )

    prior_subturns = current_turn.subturns[:-1]
    live_subturn = current_turn.subturns[-1] if current_turn.subturns else None

    for subturn in prior_subturns:
        messages.append({"role": "user", "content": subturn.user_text_with_context})
        messages.append(
            {"role": "assistant", "content": _subturn_assistant_context(subturn)}
        )

    if live_subturn:
        # Only the live subturn replays full exchanges. That is where provider
        # native reasoning/tool-call payloads matter; prior subturns have
        # already been reduced to final answer + Context Notes.
        messages.append(
            {"role": "user", "content": live_subturn.user_text_with_context}
        )
        for exchange in live_subturn.exchanges:
            messages.extend(exchange.to_messages())

    return messages


# ---------------------------------------------------------------------------
# Async LLM call abstraction
# ---------------------------------------------------------------------------


async def _async_run_llm_call(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    subturn_id: str,
    exchange_idx: int,
    tool_defs: list[dict] | None = None,
    suppress_content_streaming: bool = False,
) -> tuple[object, str, str]:
    """
    Run one async LLM call (streaming) and emit token events.
    Returns (result, content_for_history, reasoning_accumulated).
    """
    acc: dict[str, str] = {"content": "", "reasoning": ""}
    token_count = 0

    def on_data(chunk: dict) -> None:
        nonlocal token_count
        if chunk.get("reasoning"):
            acc["reasoning"] += chunk["reasoning"]
            socketio.emit(
                "token",
                {
                    "type": "reasoning",
                    "text": chunk["reasoning"],
                    "turn_id": turn_id,
                },
                room=session_id,
            )
        if chunk.get("content"):
            acc["content"] += chunk["content"]
            socketio.emit(
                "token",
                {
                    "type": "irat_thinking" if suppress_content_streaming else "content",
                    "text": chunk["content"],
                    "turn_id": turn_id,
                },
                room=session_id,
            )
            token_count += 1
            if token_count % 50 == 0:
                _emit_content_snapshot(
                    session_id,
                    turn_id,
                    subturn_id,
                    exchange_idx,
                    acc["content"],
                    acc["reasoning"],
                )

    # Log the resolved dialect + endpoint URL, then the params that will be
    # sent to the API (model + default_parameters).
    _adapter = streaming_llm._adapter
    _emit_backend_log(
        session_id,
        {
            "lifecyclePortion": "main-agent",
            "dialect": getattr(_adapter, "dialect_name", _adapter.__class__.__name__),
            "endpoint": _adapter.endpoint_url(streaming_llm._endpoint),
            "model": streaming_llm._model,
        },
    )
    _main_params: dict = {}
    if streaming_llm._model:
        _main_params["model"] = streaming_llm._model
    _main_params.update(streaming_llm._default_parameters)
    if _main_params:
        _emit_backend_log(
            session_id,
            {
                "lifecyclePortion": "main-agent",
                "params": _main_params,
            },
        )
    else:
        _emit_backend_log(
            session_id,
            {
                "lifecyclePortion": "main-agent",
                "params": {},
            },
        )

    result = await streaming_llm.stream(
        sanitize_messages_for_llm(payload),
        on_data,
        tools=tool_defs if tool_defs is not None else ALL_TOOL_DEFINITIONS,
    )

    if acc["reasoning"]:
        _emit_backend_log(
            session_id,
            colored("[main agent]", "yellow")
            + f" reasoning tokens detected (len={len(acc['reasoning'])})",
        )

    _emit_content_snapshot(
        session_id, turn_id, subturn_id, exchange_idx, acc["content"], acc["reasoning"]
    )

    return result, acc["content"], acc["reasoning"]
