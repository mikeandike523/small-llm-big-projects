from __future__ import annotations

import asyncio
import logging
import threading
import uuid as _uuid_module

from flask import request
from flask_socketio import emit

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
    _make_sampler_usage_tracker,
    _make_sampler_request_logger,
    _make_sampler_reasoning_detector,
)
from src.ui_connector.socket_handler_components.session_store import (
    _load_session,
    _save_session,
)
from src.ui_connector.socket_handler_components.watchdogs import (
    _is_continuation,
    _get_open_items,
    _fetch_task_title,
)
from src.ui_connector.socket_handler_components.agent_loop import _async_agent_loop
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui
from src.utils.llm.factory import load_llm_config, make_llm_refreshing
from src.utils.request_error_formatting import classify_llm_request_error
from src.utils.session_model import Session, Turn, Subturn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task-title helpers
# ---------------------------------------------------------------------------


def _build_title_context(session: Session, current_turn: Turn) -> str | None:
    """Build a short prior-context string for task-title recomputation on continuation subturns."""
    parts: list[str] = []
    for t in session.completed_turns:
        if t.task_title:
            parts.append(f"Previous task: {t.task_title}")
    for st in current_turn.subturns[:-1]:
        user_text = (st.user_text or "").strip()
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
    """Fetch a task title and emit it if successful. Best-effort; failures are logged but not fatal."""
    try:
        title = await _fetch_task_title(
            streaming_llm,
            text,
            watchdog_params,
            on_usage=_make_sampler_usage_tracker(session_id, "task_title"),
            on_request_log=_make_sampler_request_logger(session_id, "task_title"),
            on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "task_title"),
            prior_context=prior_context,
        )
        if title:
            current_turn.task_title = title
            _emit_and_log(session_id, "task_title", {"turn_id": turn_id, "title": title})
            _save_session(session_id, session)
    except Exception:
        logger.warning("Task title fetch failed for turn %s", turn_id, exc_info=True)


# Turn-starting socket event handlers
# ---------------------------------------------------------------------------


@socketio.on("user_message")
def handle_user_message(data: dict):
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    if session_id in _state._cancel_tasks:
        emit(
            "error",
            {"message": "A turn is already in progress. Please wait or cancel first."},
        )
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    turn_id: str = data.get("clientTurnId") or ""
    if not turn_id:
        turn_id = str(_uuid_module.uuid4())

    session = _load_session(session_id)
    _session_profile = session.profile_name

    llm_config = load_llm_config(_session_profile)
    if llm_config is None:
        _emit_and_log(
            session_id,
            "error",
            {
                "message": "No active token/endpoint configured. Run `slbp token use` first.",
                "turn_id": turn_id,
            },
        )
        return

    streaming_llm = make_llm_refreshing(timeout_s=60, profile_name=_session_profile)
    return_value_max_chars: int | None = llm_config["system_params"].get(
        "return_value_max_chars"
    )
    blank_response_retries: int = llm_config["system_params"].get("blank_response_retries") or 0
    strict_dirty: bool = llm_config["system_params"].get("strict_dirty", True)
    create_file_auto_eol: str = (
        llm_config["system_params"].get("create_file_auto_eol") or "enabled_silent"
    )
    enable_patch_rewriter: bool = llm_config["system_params"].get(
        "enable_patch_rewriter", False
    )
    hotfix_gpt_aggressive_arg_fill: bool = llm_config["system_params"].get(
        "hotfix_gpt_aggressive_arg_fill", False
    )
    hotfix_gpt_strict_tool_def: bool = llm_config["system_params"].get(
        "hotfix_gpt_strict_tool_def", False
    )
    model_temperature: float | None = (llm_config.get("model_params") or {}).get("temperature")
    watchdog_params: dict = llm_config.get("watchdog_params") or {}
    summarizer_params: dict = llm_config.get("summarizer_params") or {}

    user_text_with_context = text

    followup_behavior = data.get("followup_behavior", "auto")
    _is_cont = False
    if followup_behavior == "follow-up":
        _is_cont = bool(session.completed_turns)
    elif followup_behavior == "new-task":
        _is_cont = False
    elif session.completed_turns:
        _loop_for_watchdog = asyncio.new_event_loop()
        try:
            _is_cont = _loop_for_watchdog.run_until_complete(
                _is_continuation(
                    streaming_llm,
                    session,
                    text,
                    watchdog_params,
                    on_usage=_make_sampler_usage_tracker(session_id, "continuation"),
                    on_request_log=_make_sampler_request_logger(session_id, "continuation"),
                    on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "continuation"),
                )
            )
        except Exception as _wdog_exc:
            # Load-bearing watchdog: surface the failure to the UI and abort the
            # turn rather than silently guessing new-task vs follow-up. Classify
            # the same way as the main agent loop so the user gets a real
            # message (context-limit/HTTP/network) instead of a raw repr.
            logger.exception("Continuation watchdog failed for session %s", session_id)
            _classified = classify_llm_request_error(_wdog_exc)
            if _classified["log_object"] is not None:
                _emit_backend_log(session_id, _classified["log_object"])
            _err_subturn_id = str(_uuid_module.uuid4())
            _emit_and_log(
                session_id,
                "turn_start",
                {"turn_id": turn_id, "user_text": text, "subturn_id": _err_subturn_id},
            )
            _emit_and_log(
                session_id,
                "error",
                {
                    "message": _classified["gui_message"],
                    "turn_id": turn_id,
                },
            )
            return
        finally:
            _loop_for_watchdog.close()

    subturn_id = str(_uuid_module.uuid4())
    if _is_cont:
        current_turn = session.completed_turns.pop()
        current_turn.completed = False
        current_subturn = Subturn(
            id=subturn_id,
            user_text=text,
            user_text_with_context=user_text_with_context,
            is_continuation=True,
        )
        current_turn.subturns.append(current_subturn)
        turn_id = current_turn.id
    else:
        current_subturn = Subturn(
            id=subturn_id,
            user_text=text,
            user_text_with_context=user_text_with_context,
            is_continuation=False,
        )
        current_turn = Turn(
            id=turn_id,
            subturns=[current_subturn],
        )

    session.current_turn = current_turn

    _emit_and_log(
        session_id,
        "turn_start",
        {
            "turn_id": turn_id,
            "user_text": text,
            "subturn_id": subturn_id,
        },
    )

    _existing_todos = session.session_data.get("todo_list") or []
    if not _is_cont:
        session.session_data["todo_list"] = []
        _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})
    elif _existing_todos and not _get_open_items(_existing_todos):
        session.session_data["todo_list"] = []
        _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})
    elif _existing_todos:
        _emit_and_log(
            session_id,
            "todo_list_update",
            {
                "items": _todo_format_items_for_ui(_existing_todos),
                "turn_id": turn_id,
            },
        )

    cancel_event = threading.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _state._cancel_loops[session_id] = loop

    async def _run() -> None:
        task = asyncio.current_task()
        _state._cancel_tasks[session_id] = task
        title_task: asyncio.Task | None = None
        try:
            if _is_cont:
                # Continuation subturn: fire title recomputation at subturn start.
                asyncio.create_task(
                    _maybe_fetch_task_title(
                        streaming_llm,
                        text,
                        watchdog_params,
                        session_id,
                        session,
                        current_turn,
                        turn_id,
                        prior_context=_build_title_context(session, current_turn),
                    )
                )
            else:
                # New task: fire title fetch concurrently with agent loop.
                title_task = asyncio.create_task(
                    _maybe_fetch_task_title(
                        streaming_llm,
                        text,
                        watchdog_params,
                        session_id,
                        session,
                        current_turn,
                        turn_id,
                    )
                )

            _had_tool_calls = await _async_agent_loop(
                session_id,
                session,
                streaming_llm,
                turn_id,
                current_turn,
                current_subturn,
                return_value_max_chars,
                cancel_event,
                watchdog_params=watchdog_params,
                summarizer_params=summarizer_params,
                patchrewriter_params=llm_config.get("patchrewriter_params") or {},
                blank_response_retries=blank_response_retries,
                model_temperature=model_temperature,
                strict_dirty=strict_dirty,
                create_file_auto_eol=create_file_auto_eol,
                enable_patch_rewriter=enable_patch_rewriter,
                hotfix_gpt_aggressive_arg_fill=hotfix_gpt_aggressive_arg_fill,
                hotfix_gpt_strict_tool_def=hotfix_gpt_strict_tool_def,
            )

            # For new tasks, ensure title is fetched if the concurrent task
            # hasn't completed or if it failed silently.
            if not _is_cont and not current_turn.task_title:
                await _maybe_fetch_task_title(
                    streaming_llm,
                    text,
                    watchdog_params,
                    session_id,
                    session,
                    current_turn,
                    turn_id,
                )

        except asyncio.CancelledError:
            if title_task is not None and not title_task.done():
                title_task.cancel()
            cancel_event.set()
        except Exception as exc:
            logger.exception(
                "Unhandled exception escaped _async_agent_loop entirely for session %s: %s", session_id, exc
            )
        finally:
            _state._cancel_tasks.pop(session_id, None)
            _state._cancel_loops.pop(session_id, None)

    _state._session_active_turns.add(session_id)
    try:
        loop.run_until_complete(_run())
    finally:
        _state._session_active_turns.discard(session_id)
        loop.close()


@socketio.on("force_continuation")
def handle_force_continuation(data: dict):
    """Force a continuation subturn, bypassing the continuation watchdog."""
    sid = request.sid
    session_id = _state._sid_to_session_id.get(sid)
    if not session_id:
        emit("error", {"message": "No session_id — reconnect required."})
        return

    if session_id in _state._cancel_tasks:
        emit(
            "error",
            {"message": "A turn is already in progress. Please wait or cancel first."},
        )
        return

    text = (data.get("text") or "").strip()
    if not text:
        return

    if not _state._sid_to_session_id.get(sid):
        return

    session = _load_session(session_id)

    if not session.completed_turns:
        emit("error", {"message": "No previous turn to continue."})
        return

    _session_profile = session.profile_name

    llm_config = load_llm_config(_session_profile)
    if llm_config is None:
        emit(
            "error",
            {
                "message": "No active token/endpoint configured. Run `slbp token use` first."
            },
        )
        return

    streaming_llm = make_llm_refreshing(timeout_s=60, profile_name=_session_profile)
    return_value_max_chars: int | None = llm_config["system_params"].get(
        "return_value_max_chars"
    )
    blank_response_retries: int = llm_config["system_params"].get("blank_response_retries") or 0
    strict_dirty: bool = llm_config["system_params"].get("strict_dirty", True)
    create_file_auto_eol: str = (
        llm_config["system_params"].get("create_file_auto_eol") or "enabled_silent"
    )
    enable_patch_rewriter: bool = llm_config["system_params"].get(
        "enable_patch_rewriter", False
    )
    hotfix_gpt_aggressive_arg_fill: bool = llm_config["system_params"].get(
        "hotfix_gpt_aggressive_arg_fill", False
    )
    hotfix_gpt_strict_tool_def: bool = llm_config["system_params"].get(
        "hotfix_gpt_strict_tool_def", False
    )
    model_temperature: float | None = (llm_config.get("model_params") or {}).get("temperature")
    watchdog_params: dict = llm_config.get("watchdog_params") or {}
    summarizer_params: dict = llm_config.get("summarizer_params") or {}

    current_turn = session.completed_turns.pop()
    current_turn.completed = False

    subturn_id = str(_uuid_module.uuid4())
    turn_id = current_turn.id
    current_subturn = Subturn(
        id=subturn_id,
        user_text=text,
        user_text_with_context=text,
        is_continuation=True,
    )
    current_turn.subturns.append(current_subturn)
    session.current_turn = current_turn

    _emit_and_log(
        session_id,
        "turn_start",
        {
            "turn_id": turn_id,
            "user_text": text,
            "subturn_id": subturn_id,
        },
    )

    _fc_existing_todos = session.session_data.get("todo_list") or []
    if _fc_existing_todos and not _get_open_items(_fc_existing_todos):
        session.session_data["todo_list"] = []
        _emit_and_log(session_id, "todo_list_update", {"items": [], "turn_id": turn_id})
    elif _fc_existing_todos:
        _emit_and_log(
            session_id,
            "todo_list_update",
            {
                "items": _todo_format_items_for_ui(_fc_existing_todos),
                "turn_id": turn_id,
            },
        )

    cancel_event = threading.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _state._cancel_loops[session_id] = loop

    async def _run() -> None:
        task = asyncio.current_task()
        _state._cancel_tasks[session_id] = task
        try:
            # Recompute title for this continuation subturn.
            asyncio.create_task(
                _maybe_fetch_task_title(
                    streaming_llm,
                    text,
                    watchdog_params,
                    session_id,
                    session,
                    current_turn,
                    turn_id,
                    prior_context=_build_title_context(session, current_turn),
                )
            )
            await _async_agent_loop(
                session_id,
                session,
                streaming_llm,
                turn_id,
                current_turn,
                current_subturn,
                return_value_max_chars,
                cancel_event,
                watchdog_params=watchdog_params,
                summarizer_params=summarizer_params,
                patchrewriter_params=llm_config.get("patchrewriter_params") or {},
                blank_response_retries=blank_response_retries,
                model_temperature=model_temperature,
                strict_dirty=strict_dirty,
                create_file_auto_eol=create_file_auto_eol,
                enable_patch_rewriter=enable_patch_rewriter,
                hotfix_gpt_aggressive_arg_fill=hotfix_gpt_aggressive_arg_fill,
                hotfix_gpt_strict_tool_def=hotfix_gpt_strict_tool_def,
            )
        except asyncio.CancelledError:
            cancel_event.set()
        except Exception as exc:
            logger.exception(
                "Unhandled exception escaped _async_agent_loop (force_continuation) for session %s: %s",
                session_id,
                exc,
            )
        finally:
            _state._cancel_tasks.pop(session_id, None)
            _state._cancel_loops.pop(session_id, None)

    _state._session_active_turns.add(session_id)
    try:
        loop.run_until_complete(_run())
    finally:
        _state._session_active_turns.discard(session_id)
        loop.close()
