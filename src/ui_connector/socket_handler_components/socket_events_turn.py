from __future__ import annotations

import asyncio
import logging
import threading
import uuid as _uuid_module

from flask import request
from flask_socketio import emit

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
    _make_sampler_usage_tracker,
    _make_sampler_request_logger,
    _make_sampler_response_logger,
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
from src.utils.session_model import (
    SUBTURN_ORIGIN_USER,
    Session,
    Subturn,
    Turn,
)

logger = logging.getLogger(__name__)


def _load_runtime_llm_config(session_id: str, session: Session) -> dict | None:
    """Load one atomic desired-profile snapshot for a single LLM dispatch."""
    settings = runtime_settings.snapshot(session_id, session)
    config = load_llm_config(settings.profile_name)
    if config is not None:
        config["profile_revision"] = settings.profile_revision
    return config


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
            on_response=_make_sampler_response_logger(session_id, "task_title"),
            prior_context=prior_context,
        )
        if title:
            current_turn.task_title = title
            _emit_and_log(
                session_id, "task_title", {"turn_id": turn_id, "title": title}
            )
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

    turn_id: str = data.get("clientTurnId") or str(_uuid_module.uuid4())
    followup_behavior = data.get("followup_behavior", "auto")
    if not new_user_message(session_id, data, turn_id, followup_behavior):
        emit(
            "error",
            {"message": "A turn is already in progress. Please wait or cancel first."},
        )


def new_user_message(
    session_id: str,
    data: dict,
    turn_id: str,
    followup_behavior: str,
    *,
    background: bool = False,
    origin: str = SUBTURN_ORIGIN_USER,
) -> bool:
    """Admit and run one user message for a session, with no socket context.

    Returns False (and does nothing) when the session already has a turn in
    progress. With ``background=True`` the turn runs on its own thread and
    this returns as soon as the turn has been admitted. ``origin`` is
    recorded on the new subturn (see ``Subturn.origin``).
    """
    if not _state.try_reserve_turn(session_id, origin):
        logger.warning(
            "Turn reservation rejected: session_id=%s turn_id=%s followup_behavior=%s",
            session_id,
            turn_id,
            followup_behavior,
        )
        return False

    logger.info(
        "Turn reservation acquired: session_id=%s turn_id=%s followup_behavior=%s",
        session_id,
        turn_id,
        followup_behavior,
    )

    def _run_admitted() -> None:
        try:
            _handle_admitted_user_message(
                data,
                session_id,
                turn_id,
                followup_behavior,
                origin=origin,
            )
        finally:
            _state.release_turn(session_id)
            logger.info(
                "Turn reservation released: session_id=%s turn_id=%s followup_behavior=%s",
                session_id,
                turn_id,
                followup_behavior,
            )

    if not background:
        _run_admitted()
        return True

    def _run_admitted_logged() -> None:
        try:
            _run_admitted()
        except Exception:
            logger.exception(
                "Background turn failed: session_id=%s turn_id=%s",
                session_id,
                turn_id,
            )

    try:
        threading.Thread(
            target=_run_admitted_logged,
            name=f"turn-{session_id}",
            daemon=True,
        ).start()
    except BaseException:
        _state.release_turn(session_id)
        raise
    return True


def _handle_admitted_user_message(
    data: dict,
    session_id: str,
    turn_id: str,
    followup_behavior: str,
    *,
    origin: str = SUBTURN_ORIGIN_USER,
) -> None:
    text = (data.get("text") or "").strip()
    if not text:
        return

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

    streaming_llm = make_llm_refreshing(
        timeout_s=60,
        config_loader=lambda: _load_runtime_llm_config(session_id, session),
    )
    # load_llm_config() resolves every profile-scoped system.* param through the
    # registry getter, so each key below is always present with its registry
    # default already applied -- no per-callsite fallback literal needed.
    _system_params = llm_config["system_params"]
    return_value_max_chars: int | None = _system_params["return_value_max_chars"]
    blank_response_retries: int = _system_params["blank_response_retries"]
    strict_dirty: bool = _system_params["strict_dirty"]
    create_file_auto_eol: str = _system_params["create_file_auto_eol"]
    enable_patch_rewriter: bool = _system_params["enable_patch_rewriter"]
    model_temperature: float | None = (llm_config.get("model_params") or {}).get(
        "temperature"
    )
    watchdog_params: dict = llm_config.get("watchdog_params") or {}
    summarizer_params: dict = llm_config.get("summarizer_params") or {}

    user_text_with_context = text

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
                    on_request_log=_make_sampler_request_logger(
                        session_id, "continuation"
                    ),
                    on_response=_make_sampler_response_logger(
                        session_id, "continuation"
                    ),
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
                {
                    "turn_id": turn_id,
                    "user_text": text,
                    "subturn_id": _err_subturn_id,
                    "origin": origin,
                },
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
            approval_mode=session.approval_mode,
            origin=origin,
        )
        current_turn.subturns.append(current_subturn)
        turn_id = current_turn.id
    else:
        current_subturn = Subturn(
            id=subturn_id,
            user_text=text,
            user_text_with_context=user_text_with_context,
            is_continuation=False,
            approval_mode=session.approval_mode,
            origin=origin,
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
            "origin": origin,
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

    async def _run() -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Agent turn started without an asyncio task")
        _state.register_active_turn_handles(session_id, loop, task)
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
                "Unhandled exception escaped _async_agent_loop entirely for session %s: %s",
                session_id,
                exc,
            )
        finally:
            _state.clear_active_turn_handles(session_id, task)

    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
