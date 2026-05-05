from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
import pyte

from src.terminal.pty_process import PtyProcess
from src.terminal.shell_resolver import resolve_shell

_SCROLLBACK = 10_000


def _render_line(line, columns: int) -> str:
    # History lines are plain dict copies (not defaultdict), so unwritten
    # columns are absent — fall back to a space for missing cells.
    return "".join(
        getattr(line.get(x), "data", " ") for x in range(columns)
    ).rstrip()


@dataclass
class TerminalSession:
    id: str
    process: PtyProcess
    name: str
    cwd: str
    created_at: float = field(default_factory=time.time)
    _screen: pyte.HistoryScreen = field(init=False)
    _stream: pyte.ByteStream = field(init=False)
    _pyte_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._screen = pyte.HistoryScreen(80, 24, history=_SCROLLBACK)
        self._stream = pyte.ByteStream(self._screen)

    def append_output(self, data: bytes) -> None:
        with self._pyte_lock:
            self._stream.feed(data)

    def resize_screen(self, rows: int, cols: int) -> None:
        with self._pyte_lock:
            self._screen.resize(rows, cols)

    def read_lines(self, mode: str, num_lines: int | None = None) -> str:
        with self._pyte_lock:
            cols = self._screen.columns
            history = [
                _render_line(line, cols)
                for line in self._screen.history.top
            ]
            visible = [line.rstrip() for line in self._screen.display]

        if mode == "screen":
            result = visible
        elif mode == "all":
            result = history + visible
        elif mode == "head":
            all_lines = history + visible
            result = all_lines[: num_lines or 50]
        elif mode == "tail":
            all_lines = history + visible
            result = all_lines[-(num_lines or 50):]
        else:
            return f"Error: Unknown mode {mode!r}. Use head, tail, screen, or all."

        return "\n".join(result)


class TerminalSessionManager:
    """
    Thread-safe registry of live terminal sessions.

    Each session wraps a PtyProcess and a pyte.HistoryScreen that mirrors
    the rendered terminal state, enabling accurate read_open_terminal queries.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        name: str = "terminal",
        cwd: str | None = None,
        rows: int = 24,
        cols: int = 80,
        cmd: list[str] | None = None,
        terminal_id: str | None = None,
    ) -> TerminalSession:
        """
        Spawn a new shell process and register it.

        *cmd* overrides the default platform shell.
        *terminal_id* pins the session ID; a UUID is generated if omitted.
        """
        import uuid
        shell_cmd = cmd if cmd is not None else resolve_shell()
        proc = PtyProcess(shell_cmd, rows=rows, cols=cols, cwd=cwd)
        sid = terminal_id if terminal_id is not None else str(uuid.uuid4())
        session = TerminalSession(
            id=sid,
            process=proc,
            name=name,
            cwd=cwd or "",
        )
        session.resize_screen(rows, cols)
        with self._lock:
            self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[TerminalSession]:
        with self._lock:
            return list(self._sessions.values())

    def destroy(self, session_id: str) -> None:
        """Terminate the process and remove the session from the registry."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.process.terminate()

    def cleanup_dead(self) -> int:
        """Remove sessions whose process has already exited. Returns count removed."""
        with self._lock:
            dead = [
                sid
                for sid, s in self._sessions.items()
                if not s.process.is_alive()
            ]
            for sid in dead:
                del self._sessions[sid]
        return len(dead)
