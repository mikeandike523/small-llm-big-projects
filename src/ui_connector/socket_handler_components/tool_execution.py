from __future__ import annotations

import time
import threading
from typing import Any

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.ui_connector.socket_handler_components.emit import (
    _emit_and_log,
    _emit_backend_log,
    _make_sampler_usage_tracker,
    _make_sampler_request_logger,
    _make_sampler_reasoning_detector,
)
from src.ui_connector.socket_handler_components.terminal import (
    _launch_terminal_for_session,
    _read_terminal_output,
    _get_terminals_state,
)
from src.ui_connector.socket_handler_components.approval import _request_approval
from src.tools import execute_tool, check_needs_approval, get_dirty_effects, _TOOL_MAP
from src.tools import _dirty_cache
from src.tools import _file_snapshot
from src.tools.todo_list import format_items_for_ui as _todo_format_items_for_ui
from src.utils.session_model import Session, Turn, LLMExchange, ToolCallRecord
from src.utils.exceptions import ToolHangError, ToolTimeoutError


def _stub_tool_result(full_result: str, max_chars: int, session_data: dict) -> str:
    import secrets

    memory = session_data.get("memory", {})
    while True:
        code = secrets.token_hex(4)
        key = f"stubs.{code}"
        if key not in memory:
            break
    memory[key] = full_result
    total = len(full_result)
    overflow = total - max_chars
    preview = full_result[:max_chars]
    return (
        f"** STUBBED LONG RETURN VALUE **\n"
        f'(total {total} chars, session_memory_key="{key}")\n'
        f"Preview:\n\n"
        f"{preview}... (+ {overflow} more chars)"
    )


def _execute_tools(
    result: Any,
    content_for_history: str,
    session: Session,
    sid: str,
    session_id: str,
    current_turn: Turn,
    return_value_max_chars: int | None = None,
    cancel_event: threading.Event | None = None,
    tool_map: dict | None = None,
    subturn_id: str = "",
    summarizer_params: dict | None = None,
    patchrewriter_params: dict | None = None,
    strict_dirty: bool = True,
) -> LLMExchange:
    """
    Execute all tool calls in result, emit events, and build an LLMExchange record.
    Returns the exchange.
    """
    turn_id = current_turn.id
    _current_cwd = _state._session_current_cwd.get(session_id) or session.initial_cwd
    special_resources: dict = {
        "on_log": lambda msg: _emit_backend_log(session_id, msg),
        "session_id": session_id,
        "initial_cwd": session.initial_cwd,
        "session_cwd": _current_cwd,
        "on_cwd_change": None,
        "cancel_event": cancel_event,
        "create_terminal": lambda cmd, tab_name: _launch_terminal_for_session(
            session_id, cmd, tab_name
        ),
        "get_terminal_output": lambda tid, mode, num_lines=None: _read_terminal_output(
            session_id, tid, mode, num_lines
        ),
        "get_terminals_state": lambda lines=10: _get_terminals_state(session_id, lines),
        "summarizer_params": summarizer_params or {},
        "patchrewriter_params": patchrewriter_params or {},
        "on_sampler_usage": _make_sampler_usage_tracker(session_id, "tool"),
        "on_sampler_request_log": _make_sampler_request_logger(session_id, "tool"),
        "on_sampler_reasoning_detected": _make_sampler_reasoning_detector(session_id, "tool"),
    }

    def _on_cwd_change(new_path: str) -> None:
        _state._session_current_cwd[session_id] = new_path
        special_resources["session_cwd"] = new_path
        _emit_and_log(session_id, "pwd_update", {"path": new_path.replace("\\", "/")})

    special_resources["on_cwd_change"] = _on_cwd_change

    actual_tool_map = tool_map if tool_map is not None else _TOOL_MAP
    if _state._hotfix_bad_parser:
        for tc in result.tool_calls:
            if "<|channel|>" in tc.name:
                clean = tc.name.split("<|channel|>")[0]
                if clean in actual_tool_map:
                    tc.name = clean
    if _state._hotfix_void_call:
        for tc in result.tool_calls:
            module = actual_tool_map.get(tc.name)
            if module is not None:
                props = (
                    getattr(module, "DEFINITION", {})
                    .get("function", {})
                    .get("parameters", {})
                    .get("properties")
                )
                if not props and tc.arguments:
                    tc.arguments = {}

    exchange = LLMExchange(
        assistant_content=content_for_history,
        is_final=False,
    )

    try:
        for tc in result.tool_calls:
            _emit_and_log(
                session_id,
                "tool_call",
                {
                    "id": tc.id,
                    "name": tc.name,
                    "args": tc.arguments,
                    "turn_id": turn_id,
                },
            )

            tool_record = ToolCallRecord(id=tc.id, name=tc.name, args=tc.arguments)

            # Dirty cache check: block partial edits on resources modified since last read.
            _effects = get_dirty_effects(
                tc.name,
                tc.arguments,
                session_data=session.session_data,
                tool_map=actual_tool_map,
            )
            _dirty_error = _dirty_cache.check_requires_clean(
                session_id, _effects, tc.name,
                cwd=_state._session_current_cwd.get(session_id),
                strict=strict_dirty,
            )
            if _dirty_error:
                tool_record.result = _dirty_error
                exchange.tool_calls.append(tool_record)
                _emit_and_log(
                    session_id,
                    "tool_result",
                    {
                        "id": tc.id,
                        "result": _dirty_error,
                        "turn_id": turn_id,
                    },
                )
                continue

            # Patch rewrite watchdog: before the approval check, attempt to fix a
            # failing apply_patch call so the agent never sees the error.
            if (
                tc.name == "text_editor"
                and tc.arguments.get("action") == "apply_patch"
            ):
                _patch = tc.arguments.get("patch")
                _filepath = tc.arguments.get("filepath")
                _key = tc.arguments.get("key")
                if _patch and isinstance(_patch, str) and (_filepath or _key):
                    # Read the target contents for dry-run and watchdog use.
                    _contents: str | None = None
                    if _filepath:
                        try:
                            with open(_filepath, "r", encoding="utf-8", newline="") as _fh:
                                _contents = _fh.read()
                        except Exception:
                            pass
                    elif _key:
                        _mem = session.session_data.get("memory")
                        if isinstance(_mem, dict):
                            _val = _mem.get(_key)
                            if isinstance(_val, str):
                                _contents = _val

                    if _contents is not None:
                        # Quick dry-run: skip watchdog entirely if patch already applies.
                        from src.tools._text_editor_utils import (
                            _parse_patch_file as _ptf,
                            _apply_edits as _ae,
                        )
                        _patch_ok = False
                        try:
                            _hs = _ptf(_patch)
                            if _hs:
                                _ae(_contents, _hs)
                                _patch_ok = True
                        except Exception:
                            pass

                        if not _patch_ok:
                            from src.tools._patch_rewrite_watchdog import attempt_patch_fix

                            _emit_and_log(
                                session_id,
                                "patch_rewrite_start",
                                {
                                    "tool_call_id": tc.id,
                                    "turn_id": turn_id,
                                    "original_args": dict(tc.arguments),
                                },
                            )

                            _tc_id_rw = tc.id

                            def _on_rw_progress(
                                _attempt: int,
                                _max: int,
                                _tid: str = _tc_id_rw,
                            ) -> None:
                                _emit_and_log(
                                    session_id,
                                    "patch_rewrite_attempt",
                                    {
                                        "tool_call_id": _tid,
                                        "turn_id": turn_id,
                                        "attempt": _attempt,
                                        "max_attempts": _max,
                                    },
                                )

                            _fixed = attempt_patch_fix(
                                _contents, _patch, _on_rw_progress,
                                patchrewriter_params=patchrewriter_params or {},
                                on_usage=_make_sampler_usage_tracker(session_id, "patch_rewriter"),
                                on_request_log=_make_sampler_request_logger(session_id, "patch_rewriter"),
                                on_reasoning_detected=_make_sampler_reasoning_detector(session_id, "patch_rewriter"),
                            )
                            if _fixed is not None:
                                # Mutate in-place so tool_record.args also reflects
                                # the rewritten patch (same dict reference).
                                tc.arguments["patch"] = _fixed
                                _emit_and_log(
                                    session_id,
                                    "patch_rewrite_done",
                                    {
                                        "tool_call_id": tc.id,
                                        "turn_id": turn_id,
                                        "success": True,
                                        "final_patch": _fixed,
                                    },
                                )
                            else:
                                _emit_and_log(
                                    session_id,
                                    "patch_rewrite_done",
                                    {
                                        "tool_call_id": tc.id,
                                        "turn_id": turn_id,
                                        "success": False,
                                        "final_patch": None,
                                    },
                                )

            if check_needs_approval(
                tc.name,
                tc.arguments,
                tool_map=actual_tool_map,
                session_cwd=session.initial_cwd or None,
                session_current_cwd=_state._session_current_cwd.get(session_id),
                session_data=session.session_data,
            ):
                approved, redirect_message = _request_approval(
                    sid,
                    session_id,
                    tc.id,
                    tc.name,
                    tc.arguments,
                    turn_id=turn_id,
                    subturn_id=subturn_id,
                    cancel_event=cancel_event,
                )
                if not approved:
                    if cancel_event is not None and cancel_event.is_set():
                        exchange.tool_calls.append(tool_record)
                        return exchange

                    if redirect_message:
                        denial = (
                            f"Error: NOT Approved. User did not approve this action. "
                            f"User suggests: {redirect_message}"
                        )
                    else:
                        denial = (
                            "Error: NOT Approved. User did not approve this action."
                        )

                    tool_record.result = denial
                    exchange.tool_calls.append(tool_record)
                    _emit_and_log(
                        session_id,
                        "tool_result",
                        {
                            "id": tc.id,
                            "result": denial,
                            "turn_id": turn_id,
                        },
                    )
                    continue

            # Always inject on_chunk so any tool can emit progress updates.
            _tc_id = tc.id

            def _on_chunk(chunk: str, _id: str = _tc_id) -> None:
                socketio.emit(
                    "tool_result_chunk",
                    {
                        "id": _id,
                        "chunk": chunk,
                        "turn_id": turn_id,
                    },
                    room=session_id,
                )

            special_resources["on_chunk"] = _on_chunk

            # Auto-snapshot: capture original file state before the first write this session.
            _snap_cwd = special_resources.get("session_cwd")
            for _snap_path in _effects.get("dirties_files", []):
                try:
                    _file_snapshot.auto_snapshot_if_first_write(session_id, _snap_path, cwd=_snap_cwd)
                except Exception:
                    pass

            started_at = int(time.time() * 1000)
            tool_record.started_at = started_at
            _emit_and_log(
                session_id,
                "tool_call_start",
                {
                    "id": tc.id,
                    "turn_id": turn_id,
                    "started_at": started_at,
                },
            )

            try:
                tool_result = execute_tool(
                    tc.name,
                    tc.arguments,
                    session.session_data,
                    special_resources,
                    tool_map=actual_tool_map,
                )
            except ToolHangError as e:
                tool_result = f"HANG: {e}"
            except ToolTimeoutError as e:
                tool_result = f"TIMEOUT: {e}"

            finished_at = int(time.time() * 1000)
            tool_record.finished_at = finished_at
            special_resources.pop("on_chunk", None)

            _tool_module = actual_tool_map.get(tc.name)
            _no_stub = getattr(_tool_module, "NO_STUB", False)
            if (
                not _no_stub
                and return_value_max_chars is not None
                and len(tool_result) > return_value_max_chars
            ):
                tool_result = _stub_tool_result(
                    tool_result, return_value_max_chars, session.session_data
                )
                tool_record.was_stubbed = True

            tool_record.result = tool_result
            exchange.tool_calls.append(tool_record)

            # Apply dirty effects only when the tool did not return an error.
            if _effects and not tool_result.startswith("Error"):
                if _dirty_cache.apply_effects(session_id, _effects, cwd=special_resources.get("session_cwd")):
                    _emit_and_log(
                        session_id,
                        "dirty_cache_update",
                        _dirty_cache.snapshot(session_id),
                    )

            _emit_and_log(
                session_id,
                "tool_result",
                {
                    "id": tc.id,
                    "result": tool_result,
                    "turn_id": turn_id,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
            )
            if tc.name == "todo_list":
                _raw = session.session_data.get("todo_list") or []
                _emit_and_log(
                    session_id,
                    "todo_list_update",
                    {
                        "items": _todo_format_items_for_ui(_raw),
                        "turn_id": turn_id,
                    },
                )

        return exchange

    finally:
        pass
