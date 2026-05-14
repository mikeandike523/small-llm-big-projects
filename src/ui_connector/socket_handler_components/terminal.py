from __future__ import annotations

import os
import re
import threading

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import socketio
from src.terminal import PtyProcess, TerminalSession
from src.utils.env_info import format_environment_info
from src.utils.session_model import Session


def _get_terminal_meta(session_id: str) -> dict:
    if session_id not in _state._session_terminal_state_meta:
        _state._session_terminal_state_meta[session_id] = {
            "agent_last_opened": None,
            "user_last_opened": None,
            "active": None,
            "last_asked": None,
        }
    return _state._session_terminal_state_meta[session_id]


def _resolve_terminal_sentinel(session_id: str, terminal_id: str) -> tuple:
    """Resolve a sentinel string to a real terminal ID. Returns (resolved_id, error_str)."""
    if terminal_id not in _state._TERMINAL_SENTINELS:
        return terminal_id, None
    resolved = _get_terminal_meta(session_id).get(terminal_id)
    if not resolved:
        return (
            None,
            f"Error: sentinel '{terminal_id}' has no terminal associated yet in this session.",
        )
    return resolved, None


def _new_terminal_id() -> str:
    """Return an unused random 6-hex terminal ID, reserving it atomically."""
    import secrets

    with _state._terminal_id_lock:
        while True:
            tid = secrets.token_hex(3)
            if tid not in _state._terminal_session_rooms:
                # Reserve the slot so concurrent callers skip this ID.
                _state._terminal_session_rooms[tid] = ""
                return tid


def _format_cmd_display(cmd: list[str]) -> str:
    """Format a raw argv list into a human-readable command string for the UI tooltip."""
    if not cmd:
        return ""
    # If the shell wraps a command via -lc/-c, show just the inner command string.
    if len(cmd) >= 3 and cmd[1] in ("-lc", "-c"):
        return cmd[2]
    name = os.path.splitext(os.path.basename(cmd[0]))[0]
    return " ".join([name] + cmd[1:])


_HUMAN_TERMINAL_RE = re.compile(r"^Terminal (\d+)$", re.IGNORECASE)


def _next_human_terminal_name(session_id: str) -> str:
    """Return the next auto-incremented 'Terminal N' name for a human-created terminal."""
    max_n = 0
    for s in _state._terminal_manager.list_sessions():
        if _state._terminal_session_rooms.get(s.id) != session_id:
            continue
        m = _HUMAN_TERMINAL_RE.match(s.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"Terminal {max_n + 1}"


def _build_starting_environment_info(session: Session) -> str:
    """Build the one-time environment snapshot embedded in the per-session system prompt."""
    snapshot_cwd = session.initial_cwd or os.getcwd()
    return format_environment_info(
        current_cwd=snapshot_cwd,
        initial_cwd=session.initial_cwd or None,
    )


def _terminal_output_pump(
    session_id: str, terminal_session: TerminalSession, proc: PtyProcess
) -> None:
    terminal_id = terminal_session.id
    while proc.is_alive():
        data = proc.read(timeout=0.05)
        if data:
            terminal_session.append_output(data)
            socketio.emit(
                "terminal_output",
                {
                    "terminal_id": terminal_id,
                    "data": data.decode("utf-8", errors="replace"),
                },
                room=session_id,
            )

    socketio.emit(
        "terminal_exited",
        {"terminal_id": terminal_id, "exit_code": proc.exit_code},
        room=session_id,
    )
    _state._terminal_output_threads.pop(terminal_id, None)
    _state._terminal_session_rooms.pop(terminal_id, None)


def _terminal_belongs_to_session(session_id: str, terminal_id: str) -> bool:
    return (
        bool(terminal_id)
        and _state._terminal_session_rooms.get(terminal_id) == session_id
    )


def _read_terminal_output(
    session_id: str, terminal_id: str, mode: str, num_lines: int | None
) -> str:
    terminal_id, err = _resolve_terminal_sentinel(session_id, terminal_id)
    if err:
        return err
    if not _terminal_belongs_to_session(session_id, terminal_id):
        return f"Error: Terminal {terminal_id!r} not found in this session."
    session = _state._terminal_manager.get(terminal_id)
    if session is None:
        return f"Error: Terminal {terminal_id!r} not found."
    return session.read_lines(mode, num_lines)


def _launch_terminal_for_session(session_id: str, cmd: list[str], name: str) -> str:
    """
    Spawn *cmd* directly in a new PTY tab. Returns the terminal ID.
    Emits terminal_open_panel (expand the side panel) then terminal_created.
    Called from the open_in_terminal tool via special_resources["create_terminal"].
    """
    cwd = _state._session_current_cwd.get(session_id) or os.getcwd() or None
    terminal_id = _new_terminal_id()
    try:
        session = _state._terminal_manager.create(
            name=name, cwd=cwd, rows=24, cols=80, cmd=cmd, terminal_id=terminal_id
        )
        _state._terminal_session_rooms[session.id] = session_id
    except Exception:
        _state._terminal_session_rooms.pop(terminal_id, None)
        raise
    _state._terminal_opened_by[session.id] = "agent"
    meta = _get_terminal_meta(session_id)
    meta["agent_last_opened"] = session.id
    t = threading.Thread(
        target=_terminal_output_pump,
        args=(session_id, session, session.process),
        daemon=True,
    )
    _state._terminal_output_threads[session.id] = t
    socketio.emit("terminal_open_panel", {}, room=session_id)
    socketio.emit(
        "terminal_created",
        {
            "terminal_id": session.id,
            "name": name,
            "cmd_display": _format_cmd_display(session.cmd),
        },
        room=session_id,
    )
    t.start()
    return session.id


def _get_terminals_state(session_id: str, lines: int) -> list:
    """Build the check_terminal_state payload for all terminals in this session."""
    lines = max(0, min(100, lines))
    meta = _get_terminal_meta(session_id)
    priority = ("agent_last_opened", "user_last_opened", "active", "last_asked")

    result = []
    for ts in _state._terminal_manager.list_sessions():
        if _state._terminal_session_rooms.get(ts.id) != session_id:
            continue
        special_status = None
        for status in priority:
            if meta.get(status) == ts.id:
                special_status = status
                break
        entry = {
            "id": ts.id,
            "name": ts.name,
            "starting_command": _format_cmd_display(ts.cmd),
            "opened_by": _state._terminal_opened_by.get(ts.id, "user"),
            "special_status": special_status,
        }
        if lines > 0:
            entry[f"last_{lines}_lines"] = ts.read_lines("tail", lines)
        result.append(entry)
    return result
