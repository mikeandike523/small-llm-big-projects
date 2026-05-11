from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import _emit_and_log
from src.ui_connector.socket_handler_components.llm import _build_llm_payload, _subturn_final_response
from src.logic.system_prompt import get_selector_candidate_entries
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
    max_tokens: int | None,
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
        result = await asyncio.to_thread(streaming_llm.fetch, messages, max_tokens)
        title = (result.content or "").strip()
        if not title:
            return None
        if len(title) > _state.TITLE_MAX_CHARS:
            title = title[:_state.TITLE_MAX_CHARS - 1] + "…"
        return title
    except Exception as exc:
        logger.warning("Task title LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Final-answer watchdog
# ---------------------------------------------------------------------------

def _messages_to_watchdog_transcript(messages: list[dict]) -> str:
    """Render stripped messages into plain text for the final-answer watchdog."""
    lines: list[str] = []
    for idx, msg in enumerate(messages, start=1):
        role = msg.get("role", "?")
        lines.append(f"[Message {idx}] {role.upper()}")

        content = _truncate_watchdog_text(msg.get("content") or "", 700).strip()
        if content:
            lines.append(content)

        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                name = tc.get("function", {}).get("name", "")
                args = _truncate_watchdog_text(tc.get("function", {}).get("arguments", "") or "", 400)
                lines.append(f"Tool Call: {name}")
                if args:
                    lines.append(f"Args: {args}")
        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id:
                lines.append(f"Tool Call ID: {tc_id}")

        lines.append("")

    return "\n".join(lines).strip()


async def _is_sufficient_final_answer(
    streaming_llm: StreamingLLM,
    session: Session,
    current_turn: Turn,
    current_subturn: Subturn,
    candidate_text: str,
    watchdog_max_tokens: int | None,
) -> bool:
    """Ask a small out-of-band evaluator whether candidate_text is a sufficient final answer."""
    payload = _build_llm_payload(session, current_turn)
    transcript = _messages_to_watchdog_transcript(payload)

    todo_list = session.session_data.get("todo_list") or []
    open_items = _get_open_items(todo_list)
    closed_items = _get_closed_items(todo_list)
    todo_status = (
        f"todo_items_created={len(todo_list)}, "
        f"todo_items_closed={len(closed_items)}, "
        f"todo_items_open={len(open_items)}"
    )
    subturn_had_tool_calls = current_subturn.count_tool_calls() > 0

    messages = [
        {
            "role": "system",
            "content": (
                "You are evaluating whether an assistant's latest reply is a valid final response "
                "that ends the current subturn.\n"
                "\n"
                "Reply with exactly one word: YES or NO.\n"
                "\n"
                "Reply YES if the latest reply is any of the following:\n"
                "  - A direct final answer or summary of completed work.\n"
                "  - A question or request for clarification directed at the user.\n"
                "  - A statement that the task cannot be completed, with a clear explanation.\n"
                "\n"
                "Reply NO if the reply is only a partial status update, reasoning fragment, "
                "or interim step that does not resolve the subturn."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{current_subturn.user_text}\n\n"
                f"Turn facts:\n"
                f"- had_tool_calls: {subturn_had_tool_calls}\n"
                f"- {todo_status}\n\n"
                f"Prior conversation transcript (already stripped/truncated for evaluator use):\n"
                f"{transcript or '(empty)'}\n\n"
                f"Latest assistant reply to evaluate:\n{candidate_text}"
            ),
        },
    ]
    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, watchdog_max_tokens)
        decision = (result.content or "").strip().upper()
        return decision == "YES"
    except Exception as exc:
        logger.warning("Final-answer watchdog LLM call failed: %s", exc)
        return False


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
        result = streaming_llm.fetch(messages)
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
) -> None:
    """Async: generate a compaction for a completed subturn, store it, and emit to frontend."""
    compaction = await asyncio.to_thread(
        _compute_subturn_compaction, streaming_llm, current_subturn, final_content
    )
    current_subturn.detailed_summary = compaction
    _emit_and_log(session_id, "subturn_compaction", {
        "turn_id": turn_id,
        "subturn_id": current_subturn.id,
        "compaction": compaction,
    })


# ---------------------------------------------------------------------------
# Continuation watchdog
# ---------------------------------------------------------------------------

async def _is_continuation(
    streaming_llm: StreamingLLM,
    session: Session,
    user_text: str,
    watchdog_max_tokens: int | None,
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
    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, watchdog_max_tokens)
        decision = (result.content or "").strip().upper()
        return decision != "YES"
    except Exception as exc:
        logger.warning("Continuation watchdog LLM call failed: %s", exc)
        return False


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
            user = user[:_state._SKILL_SELECTOR_TURN_CHARS] + "..."
        if len(assistant) > _state._SKILL_SELECTOR_TURN_CHARS:
            assistant = assistant[:_state._SKILL_SELECTOR_TURN_CHARS] + "..."
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
    watchdog_max_tokens: int | None,
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

    try:
        result = await asyncio.to_thread(streaming_llm.fetch, messages, watchdog_max_tokens)
        response = (result.content or "").strip().lower()
        if not response or response == "none":
            return []
        selected_ids = {f.strip() for f in response.split(",") if f.strip()}
        return [e for e in selector_candidates if e["id"] in selected_ids]
    except Exception as exc:
        logger.warning("Skill selector watchdog failed: %s", exc)
        return []
