from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _make_sampler_usage_tracker,
)
from src.ui_connector.socket_handler_components.llm import (
    _subturn_final_response,
)
from src.logic.system_prompt import get_selector_candidate_entries
from src.utils.llm.factory import _call_sampler
from src.utils.llm.streaming import StreamingLLM
from src.utils.session_model import Session, Turn, Subturn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Todo list helpers
# ---------------------------------------------------------------------------


def _get_closed_items(todo_list: list) -> list[str]:
    return [it["text"] for it in todo_list if it.get("status") == "closed"]


def _get_open_items(todo_list: list) -> list[str]:
    result = []
    for item in todo_list:
        sub = item.get("sub_list")
        if sub is not None:
            result.extend(_get_open_items(sub))
        elif item.get("status") != "closed":
            result.append(item["text"])
    return result


# ---------------------------------------------------------------------------
# Task title helpers
# ---------------------------------------------------------------------------


def _truncate_watchdog_text(text: Any, max_chars: int) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    if len(text) <= max_chars:
        return text
    overflow = len(text) - max_chars
    return text[:max_chars] + f"... ({overflow} more chars)"


async def _fetch_task_title(
    streaming_llm: StreamingLLM,
    user_text: str,
    watchdog_params: dict,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
) -> str | None:
    """Make a non-streaming LLM call to generate a short title for the task."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a labelling assistant. "
                "Given a user request, output a short title of 3-7 words that captures "
                "the essence of what the user wants to accomplish. "
                "Output ONLY the title — no punctuation, no quotes, no explanation."
            ),
        },
        {"role": "user", "content": user_text},
    ]
    try:
        result = await asyncio.to_thread(
            _call_sampler, streaming_llm, messages, watchdog_params, on_usage,
            on_request_log, on_reasoning_detected,
        )
        title = (result.content or "").strip()
        if not title:
            return None
        if len(title) > _state.TITLE_MAX_CHARS:
            title = title[: _state.TITLE_MAX_CHARS - 1] + "…"
        return title
    except Exception as exc:
        logger.warning("Task title LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Final-answer selector
# ---------------------------------------------------------------------------


async def _select_best_final_answer(
    streaming_llm: StreamingLLM,
    user_text: str,
    candidates: list[str],
    watchdog_params: dict,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
) -> int:
    """Pick the best final answer among candidate responses.

    Returns a 0-based index into ``candidates``. Callers should skip this call
    entirely when there is only one candidate. Falls back to the last candidate
    on any error or unparseable response (mirrors the old "use the most recent
    acceptable response" bias).
    """
    if not candidates:
        return 0
    if len(candidates) == 1:
        return 0

    numbered = [
        f"[Response {i}]:\n{_truncate_watchdog_text(text, 1500).strip()}"
        for i, text in enumerate(candidates, start=1)
    ]
    responses_block = "\n\n".join(numbered)

    messages = [
        {
            "role": "system",
            "content": (
                "You are selecting the single best final reply to send to a user, chosen "
                "from several candidate responses an assistant produced while working on "
                "the task.\n\n"
                "Pick the response that most completely and clearly answers the user's "
                "request as a standalone final reply. Prefer a finished answer or summary "
                "over an interim status update, a reasoning fragment, or a note about work "
                "still in progress.\n\n"
                f"The candidates are numbered 1 to {len(candidates)}.\n"
                "Output ONLY the number of the best response. Nothing else."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{user_text}\n\n"
                f"Candidate responses:\n{responses_block}"
            ),
        },
    ]
    # NOTE: this is a load-bearing watchdog. A failed LLM call must propagate so
    # the agent loop surfaces it as a UI error rather than silently degrading.
    # Only an unparseable-but-successful response falls back to the last candidate.
    result = await asyncio.to_thread(
        _call_sampler, streaming_llm, messages, watchdog_params, on_usage,
        on_request_log, on_reasoning_detected,
    )
    raw = (result.content or "").strip()
    match = re.search(r"\d+", raw)
    if match:
        idx = int(match.group()) - 1
        if 0 <= idx < len(candidates):
            return idx
    logger.warning(
        "Final-answer selector returned unparseable result %r — using last candidate", raw
    )
    return len(candidates) - 1


# ---------------------------------------------------------------------------
# Compaction helpers
# ---------------------------------------------------------------------------


def _format_tool_calls_for_compaction(subturn: Subturn) -> str:
    """Format all tool calls in a subturn into a readable string for the compaction prompt."""
    MAX_ARG_CHARS = 300
    MAX_RESULT_CHARS = 500
    lines: list[str] = []
    for ex in subturn.exchanges:
        for tc in ex.tool_calls:
            args_str = json.dumps(tc.args, ensure_ascii=False)
            if len(args_str) > MAX_ARG_CHARS:
                args_str = args_str[:MAX_ARG_CHARS] + "..."
            result_str = tc.result or "(no result)"
            if len(result_str) > MAX_RESULT_CHARS:
                result_str = result_str[:MAX_RESULT_CHARS] + "..."
            lines.append(f"{tc.name}({args_str})")
            lines.append(f"  Result: {result_str}")
    return "\n".join(lines)


def _compute_subturn_compaction(
    streaming_llm: StreamingLLM,
    subturn: Subturn,
    final_content: str,
    summarizer_params: dict,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
) -> str:
    """Synchronous: call LLM to produce a context annotation for a completed subturn."""
    tool_calls_text = _format_tool_calls_for_compaction(subturn)
    messages = [
        {
            "role": "system",
            "content": (
                "You are writing a context annotation for a completed AI agent work unit.\n"
                "Output EXACTLY this format, nothing else:\n\n"
                "Tools used:\n"
                "- {tool_name}: {one-sentence: why called and what it accomplished}\n"
                "Memory changes:\n"
                "- {key or path}: {one-sentence: what was stored and why}\n"
                "Notable insights:\n"
                "- {any important problem-solving strategy, decision, or approach used}\n\n"
                "Rules:\n"
                "- List every tool call under 'Tools used:'\n"
                "- Under 'Memory changes:' list only session_memory writes; "
                "if none, write a single line: (none)\n"
                "- Under 'Notable insights:' list any non-obvious approaches; "
                "if none, write a single line: (none)\n"
                "- One bullet per item, one sentence each\n"
                "- Output nothing else"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Final response:\n{final_content}\n\n"
                f"Tool calls made:\n{tool_calls_text}"
            ),
        },
    ]
    try:
        result = _call_sampler(
            streaming_llm, messages, summarizer_params, on_usage,
            on_request_log, on_reasoning_detected,
        )
        text = (result.content or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("Subturn compaction LLM call failed: %s", exc)
    return "(context annotation unavailable)"


async def _generate_and_store_compaction(
    streaming_llm: StreamingLLM,
    session_id: str,
    turn_id: str,
    current_subturn: Subturn,
    final_content: str,
    summarizer_params: dict,
    on_request_log=None,
    on_reasoning_detected=None,
) -> None:
    """Async: generate a compaction for a completed subturn, store it, and emit to frontend."""
    _on_usage = _make_sampler_usage_tracker(session_id, "summarizer")
    compaction = await asyncio.to_thread(
        _compute_subturn_compaction,
        streaming_llm,
        current_subturn,
        final_content,
        summarizer_params,
        _on_usage,
        on_request_log,
        on_reasoning_detected,
    )
    current_subturn.detailed_summary = compaction
    _emit_and_log(
        session_id,
        "subturn_compaction",
        {
            "turn_id": turn_id,
            "subturn_id": current_subturn.id,
            "compaction": compaction,
        },
    )


# ---------------------------------------------------------------------------
# Continuation watchdog
# ---------------------------------------------------------------------------


async def _is_continuation(
    streaming_llm: StreamingLLM,
    session: Session,
    user_text: str,
    watchdog_params: dict,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
) -> bool:
    """Decide whether a new user message is a follow-up continuation of the previous turn."""
    last_turn = session.completed_turns[-1]
    last_subturn = last_turn.subturns[-1] if last_turn.subturns else None
    if last_subturn:
        last_response = _subturn_final_response(last_subturn)
    else:
        last_response = last_turn.condensed_assistant or ""

    messages = [
        {
            "role": "system",
            "content": (
                "You are deciding whether a new user message is an entirely new, independent task "
                "or a continuation of the previous conversation.\n"
                "Reply with exactly one word: YES or NO.\n"
                "YES = the message is a completely new, unrelated task that has nothing to do with "
                "the previous response.\n"
                "NO  = the message continues, extends, questions, or builds on the previous response.\n"
                "When in doubt, reply NO."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Previous assistant response:\n{last_response}\n\n"
                f"New user message:\n{user_text}"
            ),
        },
    ]
    # Load-bearing: a failed LLM call must propagate so the caller can surface it
    # as a UI error and abort the turn rather than silently treating it as new-task.
    result = await asyncio.to_thread(
        _call_sampler, streaming_llm, messages, watchdog_params, on_usage,
        on_request_log, on_reasoning_detected,
    )
    decision = (result.content or "").strip().upper()
    return decision != "YES"


# ---------------------------------------------------------------------------
# Skill selector watchdog
# ---------------------------------------------------------------------------


def _build_skill_selector_transcript(session: Session) -> str:
    """Format completed turns into a short context transcript for the skill selector."""
    if not session.completed_turns:
        return ""
    lines: list[str] = []
    for i, turn in enumerate(session.completed_turns, start=1):
        user = (turn.condensed_user or "").strip()
        assistant = (turn.condensed_assistant or "").strip()
        if len(user) > _state._SKILL_SELECTOR_TURN_CHARS:
            user = user[: _state._SKILL_SELECTOR_TURN_CHARS] + "..."
        if len(assistant) > _state._SKILL_SELECTOR_TURN_CHARS:
            assistant = assistant[: _state._SKILL_SELECTOR_TURN_CHARS] + "..."
        lines.append(f"[Turn {i}]")
        lines.append(f"User: {user}")
        lines.append(f"Assistant: {assistant}")
        lines.append("")
    return "\n".join(lines).strip()


async def _select_skills_for_turn(
    streaming_llm: StreamingLLM,
    session: Session,
    user_text: str,
    skill_registry: list[dict],
    watchdog_params: dict,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
) -> list[dict]:
    """Run a lightweight LLM call to decide which skills to inject for this turn."""
    selector_candidates = get_selector_candidate_entries(skill_registry)
    if not selector_candidates:
        return []

    skill_list_lines = [
        f"- {e['id']} -- {e['name']} -- {e['blurb']}" for e in selector_candidates
    ]
    skill_list = "\n".join(skill_list_lines)

    transcript = _build_skill_selector_transcript(session)
    context_block = ""
    if transcript:
        context_block = f"Conversation so far:\n{transcript}\n\n"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a skill selector. Given a conversation transcript and the current "
                "user request, decide which skill guides (if any) should be loaded to help "
                "complete the request.\n\n"
                "Each skill is a specialized guide with instructions for a specific task type.\n\n"
                f"Available skills:\n{skill_list}\n\n"
                "Output ONLY a comma-separated list of skill ids to load, or the single word "
                "'none' if no skills are needed. Return only ids or 'none'."
            ),
        },
        {
            "role": "user",
            "content": f"{context_block}Current request: {user_text}",
        },
    ]

    # Load-bearing: a failed LLM call must propagate so the agent loop surfaces it
    # as a UI error rather than silently running the turn with no skills loaded.
    result = await asyncio.to_thread(
        _call_sampler, streaming_llm, messages, watchdog_params, on_usage,
        on_request_log, on_reasoning_detected,
    )
    response = (result.content or "").strip().lower()
    if not response or response == "none":
        return []
    selected_ids = {f.strip() for f in response.split(",") if f.strip()}
    return [e for e in selector_candidates if e["id"] in selected_ids]
