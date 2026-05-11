from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import _emit_and_log, _emit_content_snapshot
from src.ui_connector.socket_handler_components.session_store import _get_session_system_prompt
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
            messages.append({"role": "assistant", "content": _subturn_assistant_context(subturn)})

    prior_subturns = current_turn.subturns[:-1]
    live_subturn = current_turn.subturns[-1] if current_turn.subturns else None

    for subturn in prior_subturns:
        messages.append({"role": "user", "content": subturn.user_text_with_context})
        messages.append({"role": "assistant", "content": _subturn_assistant_context(subturn)})

    if live_subturn:
        messages.append({"role": "user", "content": live_subturn.user_text_with_context})
        for exchange in live_subturn.exchanges:
            messages.extend(exchange.to_messages())

    return messages


# ---------------------------------------------------------------------------
# Context-limit detection helpers
# ---------------------------------------------------------------------------

def _is_context_limit_error(exc: Exception) -> bool:
    try:
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        response = exc.response
        if response is None:
            return False
        if response.status_code not in (400, 413, 422):
            return False
        body = response.text.lower()
        return any(kw in body for kw in _state._CONTEXT_LIMIT_KEYWORDS)
    except Exception:
        return False


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
    record: bool = False,
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
            socketio.emit("token", {
                "type": "reasoning", "text": chunk["reasoning"],
                "turn_id": turn_id,
            }, room=session_id)
        if chunk.get("content"):
            acc["content"] += chunk["content"]
            if not suppress_content_streaming:
                socketio.emit("token", {
                    "type": "content", "text": chunk["content"],
                    "turn_id": turn_id,
                }, room=session_id)
            token_count += 1
            if token_count % 50 == 0:
                _emit_content_snapshot(session_id, turn_id, subturn_id, exchange_idx, acc["content"], acc["reasoning"])

    result = await streaming_llm.stream(
        sanitize_messages_for_llm(payload), on_data,
        tools=(tool_defs if tool_defs is not None else ALL_TOOL_DEFINITIONS),
        record=record,
    )
    _emit_content_snapshot(session_id, turn_id, subturn_id, exchange_idx, acc["content"], acc["reasoning"])

    if result.trace is not None:
        result.trace.turn_id = turn_id
        result.trace.exchange_idx = exchange_idx
        buf = _state._session_trace_buffers.get(session_id)
        if buf is not None:
            buf.append(result.trace)

    return result, acc["content"], acc["reasoning"]


async def _async_run_llm_call_with_retry(
    streaming_llm: StreamingLLM,
    payload: list[dict],
    session_id: str,
    turn_id: str,
    subturn_id: str,
    exchange_idx: int,
    tool_defs: list[dict] | None = None,
    suppress_content_streaming: bool = False,
    record: bool = False,
) -> tuple[object, str, str]:
    """Run an async LLM call; surfaces a user-friendly error on context-limit."""
    try:
        return await _async_run_llm_call(streaming_llm, payload, session_id, turn_id, subturn_id, exchange_idx, tool_defs, suppress_content_streaming, record=record)
    except Exception as exc:
        if _is_context_limit_error(exc):
            raise RuntimeError(
                "Context limit exceeded — the conversation is too long for the model's context window.\n"
                "Please start a new session or shorten the conversation."
            ) from exc
        raise


# ---------------------------------------------------------------------------
# Trace save helpers
# ---------------------------------------------------------------------------

def _build_traces_xml(session_id: str, entries: list) -> str:
    """Serialize a list of TraceEntry objects to an XML string."""
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone

    root = ET.Element("traces")
    root.set("session_id", session_id)
    root.set("saved_at", datetime.now(timezone.utc).isoformat())

    for entry in entries:
        trace_el = ET.SubElement(root, "trace")
        trace_el.set("turn_id", entry.turn_id)
        trace_el.set("exchange_idx", str(entry.exchange_idx))
        trace_el.set("captured_at", str(entry.captured_at))

        req_el = ET.SubElement(trace_el, "request")
        req_el.text = json.dumps(entry.request_payload, ensure_ascii=False)

        resp_el = ET.SubElement(trace_el, "response")
        ET.SubElement(resp_el, "content").text = entry.content
        ET.SubElement(resp_el, "reasoning").text = entry.reasoning

        tcs_el = ET.SubElement(resp_el, "tool_calls")
        for tc in entry.tool_calls:
            tc_el = ET.SubElement(tcs_el, "tool_call")
            tc_el.set("id", tc.id)
            tc_el.set("name", tc.name)
            ET.SubElement(tc_el, "arguments").text = json.dumps(tc.arguments, ensure_ascii=False)

        if entry.usage is not None:
            ET.SubElement(resp_el, "usage").text = json.dumps(entry.usage, ensure_ascii=False)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def _rotate_traces_folder() -> None:
    """Delete oldest trace files until the folder is within _trace_folder_max_bytes."""
    if _state._trace_folder_max_bytes is None:
        return
    from pathlib import Path
    files = sorted(
        Path(_state._traces_dir).glob("*.xml"),
        key=lambda p: p.stat().st_mtime,
    )
    total = sum(f.stat().st_size for f in files)
    while total > _state._trace_folder_max_bytes and files:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)
