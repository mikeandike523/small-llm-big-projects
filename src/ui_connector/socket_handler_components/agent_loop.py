from __future__ import annotations

import asyncio
import logging
import sys
import threading

from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
    _make_sampler_usage_tracker,
    _make_sampler_request_logger,
    _make_sampler_reasoning_detector,
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
    _async_run_llm_call,
)
from src.ui_connector.socket_handler_components.watchdogs import (
    _get_open_items,
    _get_closed_items,
    _select_best_final_answer,
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
from src.utils.request_error_formatting import classify_llm_request_error
from src.utils.session_model import Session, Turn, Subturn, LLMExchange
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui
from src.tools.todo_list import format_todo_tree as _todo_format_tree

logger = logging.getLogger(__name__)


async def _async_agent_loop(
    session_id: str,
    session: Session,
    streaming_llm: StreamingLLM,
    turn_id: str,
    current_turn: Turn,
    current_subturn: Subturn,
    return_value_max_chars: int | None,
    cancel_event: threading.Event,
    watchdog_params: dict | None = None,
    summarizer_params: dict | None = None,
    patchrewriter_params: dict | None = None,
    blank_response_retries: int = 0,
    model_temperature: float | None = None,
    strict_dirty: bool = True,
    create_file_auto_eol: str | None = None,
    enable_patch_rewriter: bool = False,
) -> None:
    """
    Main agentic loop. Runs inside a private asyncio event loop in the SocketIO thread.
    """
    had_tool_calls = False
    had_todo_items = False
    final_summary_reprompt_sent = False
    # Every non-blank, no-tool response is collected here; the selector picks the
    # best one when the turn is ready to end. Each entry:
    #   {content, reasoning, subturn_id, exchange_idx, was_irat}
    final_answer_candidates: list[dict] = []
    blank_nudge_sent = False
    was_cancelled = False
    last_assistant_content = ""
    turn_completed = False
    blank_retry_count = 0
    # Set when the LLM call itself fails (HTTP error, network error, context
    # limit, or an unexpected exception) — distinct from user cancellation.
    # See src.utils.request_error_formatting.classify_llm_request_error.
    abnormal_end: dict | None = None

    session_tool_defs = _get_session_tool_defs(session_id)
    session_tool_map = _get_session_tool_map(session_id)

    skill_registry = _get_session_skill_registry(session_id)
    baseline_skills = _get_autoloaded_session_skills(session_id)
    baseline_skill_ids = {entry["id"] for entry in baseline_skills}

    # The try spans skill selection too: the skill selector is a load-bearing
    # watchdog, so its failures must reach the finally's error-emit path below.
    try:
        # Skill selection: run at the start of every subturn so that
        # continuations benefit from fresh context (prior subturns of the
        # current turn are included in the transcript).
        selected_skills = await _select_skills_for_turn(
            streaming_llm,
            session,
            current_subturn.user_text,
            skill_registry,
            watchdog_params or {},
            on_usage=_make_sampler_usage_tracker(session_id, "skill_selector"),
            on_request_log=_make_sampler_request_logger(session_id, "skill_selector"),
            on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "skill_selector"),
            current_turn=current_turn,
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
        if loaded_skills:
            _emit_and_log(
                session_id,
                "skills_loaded",
                {
                    "turn_id": turn_id,
                    "subturn_id": current_subturn.id,
                    "skill_names": [entry["name"] for entry in loaded_skills],
                },
            )
        active_skills_section = (
            build_injected_skills_section(turn_only_skills) if turn_only_skills else ""
        )

        while True:
            if cancel_event.is_set():
                was_cancelled = True
                break

            is_interim_call = (
                had_tool_calls or bool(current_subturn.exchanges) or current_subturn.is_continuation
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
                    await _async_run_llm_call(
                        streaming_llm,
                        payload,
                        session_id=session_id,
                        turn_id=turn_id,
                        subturn_id=current_subturn.id,
                        exchange_idx=exchange_idx,
                        tool_defs=session_tool_defs,
                        suppress_content_streaming=session.interim_response_as_thinking
                        and is_interim_call,
                    )
                )
            except asyncio.CancelledError:
                was_cancelled = True
                raise
            except Exception as exc:
                # Covers ContextLimitExceededError, httpx.HTTPStatusError,
                # httpx.RequestError (connection/timeout), and anything else the
                # LLM call can raise — classify_llm_request_error dispatches on
                # the concrete type.
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                abnormal_end = classify_llm_request_error(exc)
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
                        session_id,
                        current_turn,
                        return_value_max_chars,
                        cancel_event,
                        session_tool_map,
                        current_subturn.id,
                        summarizer_params or {},
                        patchrewriter_params or {},
                        strict_dirty,
                        create_file_auto_eol,
                        enable_patch_rewriter,
                    )
                except asyncio.CancelledError:
                    cancel_event.set()
                    was_cancelled = True
                    raise

                exchange.reasoning = reasoning
                exchange.reasoning_native = result.reasoning_native
                had_tool_calls = True
                blank_nudge_sent = False
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
                            streaming_llm, session_id, turn_id, current_subturn, reason,
                            summarizer_params or {},
                            on_request_log=_make_sampler_request_logger(session_id, "summarizer"),
                            on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "summarizer"),
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
            if not content_for_history.strip():
                # Silent retry: re-run without appending anything to history.
                # Skip retries when temperature=0 (deterministic — would loop forever).
                temp_allows_retry = model_temperature is None or model_temperature > 0
                if temp_allows_retry and blank_retry_count < blank_response_retries:
                    blank_retry_count += 1
                    _emit_backend_log(
                        session_id,
                        colored("[WARNING]", "yellow")
                        + f" Blank response — silent retry {blank_retry_count}/{blank_response_retries}",
                    )
                    continue
                if not blank_nudge_sent:
                    existing_open = _get_open_items(session.session_data.get("todo_list") or [])
                    if existing_open:
                        _emit_backend_log(
                            session_id,
                            colored("[WARNING]", "yellow")
                            + " Blank response with open todos — skipping nudge, letting todo reprompt handle it",
                        )
                        # Fall through: unclosed-todo block below will inject the continuation.
                    else:
                        blank_nudge_sent = True
                        blank_retry_count = 0
                        _emit_backend_log(
                            session_id,
                            colored("[WARNING]", "yellow")
                            + " Blank response — injecting todo nudge",
                        )
                        nudge_exchange = LLMExchange(
                            assistant_content="",
                            reasoning=reasoning,
                            reasoning_native=result.reasoning_native,
                            is_final=False,
                            user_continuation=(
                                "Looks like you stopped early on a long task, please make a todo list to stay on task.."
                            ),
                        )
                        current_subturn.exchanges.append(nudge_exchange)
                        _save_session(session_id, session)
                        continue
                else:
                    _emit_backend_log(
                        session_id,
                        colored("[WARNING]", "yellow")
                        + " Second consecutive blank response — handing off to standard exit logic",
                    )
                # Fall through to unclosed-todo / final-reprompt / message_done paths.

            # No tool calls — this is a non-tool assistant response.
            if blank_retry_count > 0 and content_for_history.strip():
                _emit_backend_log(
                    session_id,
                    colored("[INFO]", "green")
                    + f" Blank retry succeeded after {blank_retry_count} attempt(s) — resuming normal flow",
                )
                blank_retry_count = 0
            blank_nudge_sent = False
            blank_retry_count = 0
            # Collect this response as a final-answer candidate. Every non-blank,
            # no-tool emission counts — including interim ones produced while todos
            # are still open — and the selector chooses the best one at the end.
            if content_for_history and content_for_history.strip():
                final_answer_candidates.append(
                    {
                        "content": content_for_history,
                        "reasoning": reasoning,
                        "reasoning_native": result.reasoning_native,
                        "subturn_id": current_subturn.id,
                        "exchange_idx": exchange_idx,
                        "was_irat": was_irat_call,
                    }
                )

            # Hard block: todos must be closed before the turn can end.
            unclosed = _get_open_items(session.session_data.get("todo_list") or [])
            if unclosed:
                tree_text = _todo_format_tree(session.session_data.get("todo_list") or [])
                continuation = f"You still have unclosed todo items. Here is the formatted list:\n\n{tree_text}"
                interim_exchange = LLMExchange(
                    assistant_content=content_for_history,
                    reasoning=reasoning,
                    reasoning_native=result.reasoning_native,
                    is_final=False,
                    user_continuation=continuation,
                )
                current_subturn.exchanges.append(interim_exchange)
                _save_session(session_id, session)
                continue

            # Todos are closed → the turn is ready to end. If any candidates were
            # collected, finalize with the best one (selector only runs when >1).
            if final_answer_candidates:
                if len(final_answer_candidates) == 1:
                    winner = final_answer_candidates[0]
                else:
                    best_idx = await _select_best_final_answer(
                        streaming_llm,
                        current_subturn.user_text,
                        [c["content"] for c in final_answer_candidates],
                        watchdog_params or {},
                        on_usage=_make_sampler_usage_tracker(session_id, "final_answer"),
                        on_request_log=_make_sampler_request_logger(session_id, "final_answer"),
                        on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "final_answer"),
                    )
                    if best_idx is None:
                        # Selector judged none of the candidates a viable final
                        # answer. Force one summary reprompt to elicit a clean
                        # answer; if we already did that, fall back to the last
                        # candidate rather than looping.
                        if not final_summary_reprompt_sent:
                            final_summary_reprompt_sent = True
                            current_subturn.exchanges.append(
                                LLMExchange(
                                    assistant_content=content_for_history,
                                    reasoning=reasoning,
                                    reasoning_native=result.reasoning_native,
                                    is_final=False,
                                    user_continuation=(
                                        "None of your responses so far is a complete final "
                                        "answer. Please provide your final summary or answer "
                                        "based on the steps you took, the tool results, and "
                                        "the previous context."
                                    ),
                                )
                            )
                            _emit_and_log(session_id, "final_reprompt", {"turn_id": turn_id})
                            _emit_and_log(session_id, "begin_final_summary", {"turn_id": turn_id})
                            _save_session(session_id, session)
                            continue
                        winner = final_answer_candidates[-1]
                    else:
                        winner = final_answer_candidates[best_idx]

                final_exchange = LLMExchange(
                    assistant_content=winner["content"],
                    reasoning=winner["reasoning"],
                    reasoning_native=winner["reasoning_native"],
                    is_final=True,
                )
                current_subturn.exchanges.append(final_exchange)
                if current_subturn.count_tool_calls() > 0:
                    await _generate_and_store_compaction(
                        streaming_llm,
                        session_id,
                        turn_id,
                        current_subturn,
                        winner["content"],
                        summarizer_params or {},
                        on_request_log=_make_sampler_request_logger(session_id, "summarizer"),
                        on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "summarizer"),
                    )
                _emit_and_log(
                    session_id,
                    "message_done",
                    {
                        "content": winner["content"],
                        "turn_id": turn_id,
                    },
                )

                # If the winner was streamed as IRAT "thinking", clear that panel so
                # the frontend promotes it from thinking to the real final answer.
                # NOTE: This is emitted AFTER message_done so the final answer appears
                # on the left before the thinking bubble clears from the right.
                if winner["was_irat"]:
                    _emit_and_log(
                        session_id,
                        "irat_thinking_clear",
                        {
                            "turn_id": turn_id,
                            "subturn_id": winner["subturn_id"],
                            "exchange_idx": winner["exchange_idx"],
                        },
                    )

                turn_completed = True
                break

            # No candidates collected (only blank no-tool responses) — rare case.
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
                    reasoning_native=result.reasoning_native,
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
                reasoning_native=result.reasoning_native,
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
                    summarizer_params or {},
                    on_request_log=_make_sampler_request_logger(session_id, "summarizer"),
                    on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "summarizer"),
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
            cancelled_marker = "[Action Cancelled by User]"
            # Append the marker as a real exchange (not just condensed_*) so
            # future _build_llm_payload() calls actually replay it, instead of
            # silently replaying blank/partial content for this subturn.
            current_subturn.exchanges.append(
                LLMExchange(assistant_content=cancelled_marker, is_final=True)
            )
            current_turn.finalize(
                session.session_data, cancelled_marker, had_todo_items
            )
            session.completed_turns.append(current_turn)
            session.current_turn = None
            _emit_and_log(
                session_id,
                "message_done",
                {"content": cancelled_marker, "turn_id": turn_id},
            )
        elif abnormal_end is not None:
            # LLM call failed (HTTP error, network error, context limit, or an
            # unexpected exception during the call). The rich diagnostic detail
            # is shown live via the "error" event and the backend log object —
            # neither survives a reload (backend_log is never persisted; the
            # "error" event only replays for ~1hr via the Redis stream) — so the
            # permanent record uses the same terse marker as the LLM history.
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(
                session.session_data.get("todo_list") or []
            )
            marker = abnormal_end["history_marker"]
            current_subturn.exchanges.append(
                LLMExchange(assistant_content=marker, is_final=True)
            )
            current_turn.finalize(session.session_data, marker, had_todo_items)
            session.completed_turns.append(current_turn)
            session.current_turn = None
            if abnormal_end["log_object"] is not None:
                _emit_backend_log(session_id, abnormal_end["log_object"])
            _emit_and_log(
                session_id,
                "error",
                {"message": abnormal_end["gui_message"], "turn_id": turn_id},
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
            err_msg = "Agent loop failed."
            marker = "[Agent Error - See Backend Logs]"
            if exc_val is not None:
                # Any exception escaping the try body lands here — not just the
                # main turn call (that path is handled above via abnormal_end).
                # This covers watchdog calls made outside the inner try, e.g.
                # _select_skills_for_turn and _select_best_final_answer, which
                # hit the LLM the same way and can raise the same
                # httpx/ContextLimitExceededError family. Classify it the same
                # way as the main-call path so both the GUI message and the
                # frontend debug log get the same structured treatment — the
                # full traceback still lands in the backend process log above
                # (exc_info=True); the frontend debug log gets the classified
                # object, not a raw string dump, to match abnormal_end and the
                # continuation-watchdog handler in socket_events_turn.py.
                classified = classify_llm_request_error(exc_val)
                err_msg = classified["gui_message"]
                marker = classified["history_marker"]
                if classified["log_object"] is not None:
                    _emit_backend_log(session_id, classified["log_object"])
            current_turn.completed = True
            current_turn.todo_snapshot = _todo_format_items_for_ui(
                session.session_data.get("todo_list") or []
            )
            current_subturn.exchanges.append(
                LLMExchange(assistant_content=marker, is_final=True)
            )
            current_turn.finalize(session.session_data, marker, had_todo_items)
            session.completed_turns.append(current_turn)
            session.current_turn = None
            # Load-bearing failures (e.g. watchdogs) surface as a real UI error,
            # not a silent blank completion.
            _emit_and_log(
                session_id,
                "error",
                {"message": err_msg, "turn_id": turn_id},
            )

        _save_session(session_id, session)
        return had_tool_calls
