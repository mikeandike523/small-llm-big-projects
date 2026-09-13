from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Any

from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
    _emit_content_snapshot,
    _get_known_max_context,
)
from src.ui_connector.socket_handler_components.session_store import (
    _get_session_system_prompt,
)
from src.tools import ALL_TOOL_DEFINITIONS
from src.utils.context_errors import (
    context_limit_log_object,
    is_context_limit_error,
    is_rate_limit_error,
)
from src.utils.exceptions import ContextReductionExhaustedError
from src.utils.llm.streaming import StreamingLLM
from src.utils.session_model import Session, Turn, Subturn

logger = logging.getLogger(__name__)

PRECUT_CONTEXT_FRACTION = 0.75
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_INITIAL_S = 1.0
RATE_LIMIT_BACKOFF_MAX_S = 8.0
RATE_LIMIT_JITTER_S = 0.25


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


def _append_closed_subturn(messages: list[dict], subturn: Subturn) -> None:
    messages.append({"role": "user", "content": subturn.user_text_with_context})
    messages.append(
        {"role": "assistant", "content": _subturn_assistant_context(subturn)}
    )


def _append_live_subturn(messages: list[dict], subturn: Subturn) -> None:
    messages.append({"role": "user", "content": subturn.user_text_with_context})
    for exchange in subturn.exchanges:
        messages.extend(exchange.to_messages())


def _build_llm_payload(
    session: Session,
    current_turn: Turn,
    skills_section: str | None = None,
    closed_current_turn_prior_subturns: int | None = None,
) -> list[dict]:
    """Assemble the message list actually sent to the LLM endpoint.

    completed_turns are always represented by closed subturn context. For the
    active turn, closed_current_turn_prior_subturns controls how many earliest
    prior subturns are reduced to final response plus Context Notes. When None,
    all prior subturns are closed, preserving the historical behavior.
    """
    system_content = _get_session_system_prompt(session.session_id)
    if skills_section:
        system_content = system_content + "\n" + skills_section
    messages: list[dict] = [{"role": "system", "content": system_content}]

    for turn in session.completed_turns:
        for subturn in turn.subturns:
            _append_closed_subturn(messages, subturn)

    prior_subturns = current_turn.subturns[:-1]
    live_subturn = current_turn.subturns[-1] if current_turn.subturns else None
    if closed_current_turn_prior_subturns is None:
        closed_current_turn_prior_subturns = len(prior_subturns)
    closed_current_turn_prior_subturns = max(
        0, min(closed_current_turn_prior_subturns, len(prior_subturns))
    )

    for idx, subturn in enumerate(prior_subturns):
        if idx < closed_current_turn_prior_subturns:
            _append_closed_subturn(messages, subturn)
        else:
            _append_live_subturn(messages, subturn)

    if live_subturn:
        _append_live_subturn(messages, live_subturn)

    return messages


def _int_token_value(value: object) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    if result < 0:
        return None
    return result


def _usage_total_tokens(usage: dict | None) -> int | None:
    """Extract total tokens from a provider usage dict, if available."""
    if not isinstance(usage, dict):
        return None

    total = _int_token_value(usage.get("total_tokens"))
    if total is not None:
        return total

    input_tokens = _int_token_value(usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _int_token_value(usage.get("prompt_tokens"))
    output_tokens = _int_token_value(usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _int_token_value(usage.get("completion_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    return input_tokens + output_tokens


def _last_exchange_total_tokens(subturn: Subturn) -> int | None:
    for exchange in reversed(subturn.exchanges):
        total = _usage_total_tokens(exchange.usage)
        if total is not None:
            return total
    return None


def _prior_subturn_token_hints(current_turn: Turn) -> list[int] | None:
    """Return per-prior-subturn token hints, or None if any hint is missing."""
    hints: list[int] = []
    for subturn in current_turn.subturns[:-1]:
        total = _last_exchange_total_tokens(subturn)
        if total is None:
            return None
        hints.append(total)
    return hints


def _initial_closed_subturn_count(
    current_turn: Turn,
    known_max_context: int | None,
) -> int:
    """Choose the starting closed-subturn count for the simple pre-cut heuristic.

    The heuristic only runs when known_max_context is set and every prior
    subturn has a valid last-exchange total token count. It walks newest to
    oldest, keeps as many recent prior subturns live as fit under
    PRECUT_CONTEXT_FRACTION of the known max context, and closes the older
    prefix. It intentionally does not estimate system prompt, tool schema,
    current subturn, or closed-summary cost.
    """
    known_max_context = _int_token_value(known_max_context)
    if known_max_context is None or known_max_context == 0:
        return 0

    hints = _prior_subturn_token_hints(current_turn)
    if hints is None:
        return 0

    budget = int(known_max_context * PRECUT_CONTEXT_FRACTION)
    live_total = 0
    keep_live = 0
    for total in reversed(hints):
        if live_total + total > budget:
            break
        live_total += total
        keep_live += 1
    return len(hints) - keep_live


def _rate_limit_sleep_s(retry_index: int) -> float:
    base = min(
        RATE_LIMIT_BACKOFF_INITIAL_S * (2 ** retry_index),
        RATE_LIMIT_BACKOFF_MAX_S,
    )
    return base + random.uniform(0, RATE_LIMIT_JITTER_S)


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
        "main-agent",
        {
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
            "main-agent",
            {
                "params": _main_params,
            },
        )
    else:
        _emit_backend_log(
            session_id,
            "main-agent",
            {
                "params": {},
            },
        )

    result = await streaming_llm.stream(
        sanitize_messages_for_llm(payload),
        on_data,
        tools=tool_defs if tool_defs is not None else ALL_TOOL_DEFINITIONS,
    )

    _emit_content_snapshot(
        session_id, turn_id, subturn_id, exchange_idx, acc["content"], acc["reasoning"]
    )

    return result, acc["content"], acc["reasoning"]


async def _async_run_llm_call_with_context_retries(
    streaming_llm: StreamingLLM,
    session: Session,
    current_turn: Turn,
    skills_section: str | None,
    session_id: str,
    turn_id: str,
    subturn_id: str,
    exchange_idx: int,
    tool_defs: list[dict] | None = None,
    suppress_content_streaming: bool = False,
) -> tuple[object, str, str]:
    """Run the main LLM call, progressively closing prior subturns on context errors.

    The first attempt usually keeps every prior subturn in the current turn "live":
    their original assistant/tool/tool-result/user-continuation messages are
    replayed through LLMExchange.to_messages(), including provider-native
    replay payloads such as reasoning_native. When model.known_max_context is
    configured and every prior subturn has usage data, a conservative pre-cut
    may start with older prior subturns already closed. If and only if a request
    fails with a context-limit-looking exception, the next attempt closes one
    more earliest prior subturn by sending only its user message and assistant
    final response plus Context Notes. This repeats until the request succeeds
    or all prior subturns have been closed.

    HTTP 429 rate-limit responses retry the same payload with exponential
    backoff plus jitter and never close additional subturns. Non-context,
    non-429 exceptions are never retried and propagate unchanged, so callers
    handle exactly the original error. If 429 retries are exhausted, the final
    429 propagates unchanged. If every context-reduction attempt fails with a
    context limit error, this raises ContextReductionExhaustedError from the
    final context exception; the final HTTP response body, when available, is
    emitted to frontend logs before the custom error is raised.
    """
    max_closable = max(0, len(current_turn.subturns) - 1)
    start_closed_count = _initial_closed_subturn_count(
        current_turn,
        _get_known_max_context(session.profile_name),
    )
    if start_closed_count:
        _emit_backend_log(
            session_id,
            "Pre-cutting prior subturns from usage hints",
            {
                "closed_prior_subturns": start_closed_count,
                "closable_prior_subturns": max_closable,
                "context_fraction": PRECUT_CONTEXT_FRACTION,
            },
        )

    for closed_count in range(start_closed_count, max_closable + 1):
        payload = _build_llm_payload(
            session,
            current_turn,
            skills_section,
            closed_current_turn_prior_subturns=closed_count,
        )
        for rate_retry in range(RATE_LIMIT_MAX_RETRIES + 1):
            try:
                return await _async_run_llm_call(
                    streaming_llm,
                    payload,
                    session_id=session_id,
                    turn_id=turn_id,
                    subturn_id=subturn_id,
                    exchange_idx=exchange_idx,
                    tool_defs=tool_defs,
                    suppress_content_streaming=suppress_content_streaming,
                )
            except Exception as exc:
                if is_rate_limit_error(exc):
                    if rate_retry >= RATE_LIMIT_MAX_RETRIES:
                        raise
                    sleep_s = _rate_limit_sleep_s(rate_retry)
                    _emit_backend_log(
                        session_id,
                        "Rate limited by provider; retrying same payload",
                        {
                            "retry": rate_retry + 1,
                            "max_retries": RATE_LIMIT_MAX_RETRIES,
                            "sleep_s": round(sleep_s, 3),
                            "closed_prior_subturns": closed_count,
                        },
                    )
                    await asyncio.sleep(sleep_s)
                    continue

                if not is_context_limit_error(exc):
                    raise

                log_object = context_limit_log_object(exc)
                if log_object is not None:
                    log_object["closed_prior_subturns"] = closed_count
                    log_object["closable_prior_subturns"] = max_closable
                    _emit_backend_log(session_id, "Context limit response", log_object)

                if closed_count >= max_closable:
                    raise ContextReductionExhaustedError(
                        "Could not make request, context exceeded, "
                        "check frontend logs for response body."
                    ) from exc

                _emit_backend_log(
                    session_id,
                    "Context limit exceeded; retrying with one more prior subturn closed",
                    {
                        "closed_prior_subturns": closed_count + 1,
                        "closable_prior_subturns": max_closable,
                    },
                )
                break

    raise ContextReductionExhaustedError(
        "Could not make request, context exceeded, check frontend logs for response body."
    )
