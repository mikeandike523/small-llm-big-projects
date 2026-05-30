from __future__ import annotations

import asyncio
import logging
import sys
import traceback
import threading

import httpx
from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
)
from src.ui_connector.socket_handler_components.session_store import (
    _save_session,
    _get_session_tool_defs,
    _get_session_tool_map,
    _get_session_skill_registry,
    _get_autoloaded_session_skills,
)
from src.ui_connector.socket_handler_components.llm import (
    _build_llm_payload,
    _async_run_llm_call_with_retry,
)
from src.ui_connector.socket_handler_components.watchdogs import (
    _get_open_items,
    _get_closed_items,
    _is_sufficient_final_answer,
    _generate_and_store_compaction,
    _select_skills_for_turn,
)
from src.ui_connector.socket_handler_components.tool_execution import _execute_tools
from src.ui_connector.app import socketio
from src.logic.system_prompt import (
    build_injected_skills_section,
    resolve_skill_dependency_closure,
)
from src.utils.llm.streaming import StreamingLLM
from src.utils.request_error_formatting import format_http_error
from src.utils.session_model import Session, Turn, Subturn, LLMExchange
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui

logger = logging.getLogger(__name__)


async def _async_agent_loop(
    sid: str,
    session_id: str,
    session: Session,
    streaming_llm: StreamingLLM,
    turn_id: str,
    current_turn: Turn,
    current_subturn: Subturn,
    return_value_max_chars: int | None,
    cancel_event: threading.Event,
    watchdog_max_tokens: int | None = None,
) -> None:
    """
    Main agentic loop. Runs inside a private asyncio event loop in the SocketIO thread.
    """
    had_tool_calls = False
    had_todo_items = False
    final_summary_reprompt_sent = False
    pending_final_candidate: tuple[str, str] | None = None
    irat_candidate_exchange: tuple[str, int] | None = None
    blank_nudge_sent = False
    was_cancelled = False
    last_assistant_content = ""
    turn_completed = False

    session_tool_defs = _get_session_tool_defs(session_id)
    session_tool_map = _get_session_tool_map(session_id)

    skill_registry = _get_session_skill_registry(session_id)
    baseline_skills = _get_autoloaded_session_skills(session_id)
    baseline_skill_ids = {entry["id"] for entry in baseline_skills}

    # Skill selection: run once on the first subturn and borrow for continuations.
    if current_subturn.is_continuation and current_turn.selected_skill_ids:
        entries_by_id = {e["id"]: e for e in skill_registry}
        selected_skills = [
            entries_by_id[sid]
            for sid in current_turn.selected_skill_ids
            if sid in entries_by_id
        ]
    else:
        selected_skills = await _select_skills_for_turn(
            streaming_llm,
            session,
            current_subturn.user_text,
            skill_registry,
            watchdog_max_tokens,
        )
        current_turn.selected_skill_ids = [e["id"] for e in selected_skills]

    turn_resolved_skills = resolve_skill_dependency_closure(
        skill_registry,
        [entry["id"] for entry in selected_skills],
    )
    turn_only_skills = [
        entry for entry in turn_resolved_skills if entry["id"] not in baseline_skill_ids
    ]
    loaded_skills = baseline_skills + turn_only_skills
    if loaded_skills and not current_subturn.is_continuation:
        _emit_and_log(
            session_id,
            "skills_loaded",
            {
                "turn_id": turn_id,
                "skill_names": [entry["name"] for entry in loaded_skills],
            },
        )
    active_skills_section = (
        build_injected_skills_section(turn_only_skills) if turn_only_skills else ""
    )

    try:
        while True:
            if cancel_event.is_set():
                was_cancelled = True
                break

            is_interim_call = (
                had_tool_calls or bool(current_subturn.exchanges)
            ) and not final_summary_reprompt_sent
            was_irat_call = session.interim_response_as_thinking and is_interim_call
            if is_interim_call:
                _emit_and_log(
                    session_id,
                    "begin_interim_stream",
                    {
                        "turn_id": turn_id,
                        "show_char_count": not session.interim_response_as_thinking,
                    },
                )

            exchange_idx = len(current_subturn.exchanges)
            payload = _build_llm_payload(
                session, current_turn, active_skills_section or None
            )

            try:
                result, content_for_history, reasoning = (
                    await _async_run_llm_call_with_retry(
                        streaming_llm,
                        payload,
                        session_id=session_id,
                        turn_id=turn_id,
                        subturn_id=current_subturn.id,
                        exchange_idx=exchange_idx,
                        tool_defs=session_tool_defs,
                        suppress_content_streaming=session.interim_response_as_thinking
                        and is_interim_call,
                        record=session.record_traces,
                    )
                )
            except asyncio.CancelledError:
                was_cancelled = True
                raise
            except httpx.HTTPStatusError as exc:
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                _emit_and_log(
                    session_id,
                    "error",
                    {
                        "message": f"LLM stream error:\n\n{format_http_error(exc)}",
                        "turn_id": turn_id,
                    },
                )
                break
            except Exception as exc:
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                _emit_and_log(
                    session_id,
                    "error",
                    {
                        "message": f"LLM stream error:\n\n{exc}",
                        "turn_id": turn_id,
                    },
                )
                break

            usage = getattr(result, "usage", None)
            if usage:
                cost = usage.get("cost")
                cost_str = ""
                if cost is not None:
                    try:
                        cost = float(cost)
                        _state._session_costs[session_id] = (
                            _state._session_costs.get(session_id, 0.0) + cost
                        )
                        total_cost = _state._session_costs[session_id]
                        socketio.emit(
                            "session_cost_update",
                            {"total_usd": total_cost},
                            room=session_id,
                        )
                        cost_str = f", cost=${cost:.6f} (session=${total_cost:.6f})"
                    except (TypeError, ValueError):
                        pass
                _emit_backend_log(
                    session_id,
                    colored("Usage: ", "cyan")
                    + f"prompt={usage.get('prompt_tokens', '?')}, "
                    f"completion={usage.get('completion_tokens', '?')}, "
                    f"total={usage.get('total_tokens', '?')}" + cost_str,
                )

            stop_reason = getattr(result, "stop_reason", None)
            _emit_backend_log(
                session_id,
                colored("Stop reason: ", "cyan") + (stop_reason or "(none reported)"),
            )

            last_assistant_content = content_for_history

            if cancel_event.is_set():
                was_cancelled = True
                break

            if result.has_tool_calls:
                try:
                    exchange = await asyncio.to_thread(
                        _execute_tools,
                        result,
                        content_for_history,
                        session,
                        sid,
                        session_id,
                        current_turn,
                        return_value_max_chars,
                        cancel_event,
                        session_tool_map,
                        current_subturn.id,
                    )
                except asyncio.CancelledError:
                    cancel_event.set()
                    was_cancelled = True
                    raise

                exchange.reasoning = reasoning
                had_tool_calls = True
                if not had_todo_items and session.session_data.get("todo_list"):
                    had_todo_items = True
                current_subturn.exchanges.append(exchange)
                _save_session(session_id, session)

                if cancel_event.is_set():
                    was_cancelled = True
                    break

                # Detect report_impossible call → end turn using the reason as final response.
                impossible_call = next(
                    (
                        tc
                        for tc in exchange.tool_calls
                        if tc.name == "report_impossible"
                    ),
                    None,
                )
                if impossible_call is not None:
                    reason = impossible_call.args.get(
                        "reason", "The task cannot be completed as requested."
                    )
                    if current_subturn.count_tool_calls() > 0:
                        await _generate_and_store_compaction(
                            streaming_llm, session_id, turn_id, current_subturn, reason
                        )
                    _emit_and_log(
                        session_id,
                        "message_done",
                        {"content": reason, "turn_id": turn_id},
                    )
                    turn_completed = True
                    break

                continue

            # Blank response guard: model emitted no content and no tool calls.
            # Inject a todo-nudge once to get it back on track; if still blank, give up.
            if not content_for_history.strip():
                if not blank_nudge_sent:
                    blank_nudge_sent = True
                    _emit_backend_log(
                        session_id,
                        colored("[WARNING]", "yellow")
                        + " Blank response with no tool calls — injecting todo nudge",
                    )
                    nudge_exchange = LLMExchange(
                        assistant_content="",
                        reasoning=reasoning,
                        is_final=False,
                        user_continuation=(
                            "Looks like you stopped early on a long task, please make a todo list to stay on task.."
                        ),
                    )
                    current_subturn.exchanges.append(nudge_exchange)
                    _save_session(session_id, session)
                    continue
                _emit_backend_log(
                    session_id,
                    colored("[WARNING]", "yellow")
                    + " Blank response after todo nudge — giving up",
                )
                # Fall through: loop will emit message_done with empty content → "(no response)" bubble.

            # No tool calls — this is a non-tool assistant response.
            is_candidate = False
            if content_for_history and content_for_history.strip():
                is_candidate = await _is_sufficient_final_answer(
                    streaming_llm,
                    session,
                    current_turn,
                    current_subturn,
                    content_for_history,
                    watchdog_max_tokens,
                )
                if is_candidate:
                    pending_final_candidate = (content_for_history, reasoning)
                    irat_candidate_exchange = (current_subturn.id, exchange_idx) if was_irat_call else None

            # Hard block: todos must be closed before the turn can end.
            unclosed = _get_open_items(session.session_data.get("todo_list") or [])
            if unclosed:
                items_text = "\n".join(
                    f"  {i + 1}. {item}" for i, item in enumerate(unclosed)
                )
                continuation = f"You still have {len(unclosed)} unclosed todo item(s). Please continue:\n{items_text}"
                interim_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=False,
                    user_continuation=continuation,
                )
                current_subturn.exchanges.append(interim_exchange)
                _save_session(session_id, session)
                continue

            if is_candidate:
                if was_irat_call:
                    _emit_and_log(
                        session_id,
                        "irat_thinking_clear",
                        {
                            "turn_id": turn_id,
                            "subturn_id": current_subturn.id,
                            "exchange_idx": exchange_idx,
                        },
                    )
                final_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=True,
                )
                current_subturn.exchanges.append(final_exchange)
                if current_subturn.count_tool_calls() > 0:
                    await _generate_and_store_compaction(
                        streaming_llm,
                        session_id,
                        turn_id,
                        current_subturn,
                        content_for_history,
                    )
                _emit_and_log(
                    session_id,
                    "message_done",
                    {
                        "content": content_for_history,
                        "turn_id": turn_id,
                    },
                )
                turn_completed = True
                break

            if pending_final_candidate is not None:
                cand_content, cand_reasoning = pending_final_candidate
                if irat_candidate_exchange is not None:
                    _emit_and_log(
                        session_id,
                        "irat_thinking_clear",
                        {
                            "turn_id": turn_id,
                            "subturn_id": irat_candidate_exchange[0],
                            "exchange_idx": irat_candidate_exchange[1],
                        },
                    )
                final_exchange = LLMExchange(
                    assistant_content=cand_content,
                    reasoning=cand_reasoning,
                    is_final=True,
                )
                current_subturn.exchanges.append(final_exchange)
                if current_subturn.count_tool_calls() > 0:
                    await _generate_and_store_compaction(
                        streaming_llm,
                        session_id,
                        turn_id,
                        current_subturn,
                        cand_content,
                    )
                _emit_and_log(
                    session_id,
                    "message_done",
                    {
                        "content": cand_content,
                        "turn_id": turn_id,
                    },
                )
                turn_completed = True
                break

            if had_tool_calls and not final_summary_reprompt_sent:
                final_summary_reprompt_sent = True
                continuation = (
                    "All action items are complete. "
                    "Please provide your final summary or answer based on the steps "
                    "you took, the tool results, and the previous context."
                )
                interim_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    is_final=False,
                    user_continuation=continuation,
                )
                current_subturn.exchanges.append(interim_exchange)
                _emit_and_log(session_id, "final_reprompt", {"turn_id": turn_id})
                _emit_and_log(session_id, "begin_final_summary", {"turn_id": turn_id})
                _save_session(session_id, session)
                continue

            # Final response: no tool calls, or response after explicit reprompt.
            if not content_for_history:
                _emit_backend_log(
                    session_id,
                    colored("[WARNING]", "yellow") + " LLM returned empty final response — bubble will not render",
                )
            final_exchange = LLMExchange(
                assistant_content=content_for_history,
                reasoning=reasoning,
                is_final=True,
            )
            current_subturn.exchanges.append(final_exchange)
            if current_subturn.count_tool_calls() > 0:
                await _generate_and_store_compaction(
                    streaming_llm,
                    session_id,
                    turn_id,
                    current_subturn,
                    content_for_history,
                )
            _emit_and_log(
                session_id,
                "message_done",
                {
                    "content": content_for_history,
                    "turn_id": turn_id,
                },
            )
            turn_completed = True
            break

    except asyncio.CancelledError:
        was_cancelled = True
        raise
    finally:
        if was_cancelled:
            current_turn.was_cancelled = True
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(
                session.session_data.get("todo_list") or []
            )
            cancelled_content = "[Action Cancelled by User]"
            current_turn.finalize(
                session.session_data, cancelled_content, had_todo_items
            )
            session.completed_turns.append(current_turn)
            session.current_turn = None
            _emit_and_log(
                session_id,
                "message_done",
                {"content": cancelled_content, "turn_id": turn_id},
            )
        elif turn_completed:
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(
                session.session_data.get("todo_list") or []
            )
            current_turn.finalize(
                session.session_data, last_assistant_content, had_todo_items
            )
            session.completed_turns.append(current_turn)
            session.current_turn = None
        else:
            logger.error(
                "Agent loop exited abnormally for session %s turn %s",
                session_id,
                turn_id,
                exc_info=True,
            )
            exc_type, exc_val, exc_tb = sys.exc_info()
            if exc_val is not None:
                tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
                _emit_backend_log(session_id, f"[SERVER ERROR] Agent loop crashed:\n{tb_str}")
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(
                session.session_data.get("todo_list") or []
            )
            current_turn.finalize(
                session.session_data, last_assistant_content, had_todo_items
            )
            session.completed_turns.append(current_turn)
            session.current_turn = None
            _emit_and_log(
                session_id,
                "message_done",
                {"content": last_assistant_content or None, "turn_id": turn_id},
            )

        _save_session(session_id, session)
        return had_tool_calls
