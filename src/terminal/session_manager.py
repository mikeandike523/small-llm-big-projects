from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from src.terminal.pty_process import PtyProcess
from src.terminal.shell_resolver import resolve_shell


@dataclass
class TerminalSession:
    id: str
    process: PtyProcess
    name: str
    cwd: str
    created_at: float = field(default_factory=time.time)


class TerminalSessionManager:
    """
    Thread-safe registry of live terminal sessions.

    Each session wraps a PtyProcess.  Sessions persist until explicitly
    destroyed or cleaned up via cleanup_dead().  A future socket layer will
    map session IDs to Socket.IO rooms for bidirectional I/O streaming.
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
    ) -> TerminalSession:
        """
        Spawn a new shell process and register it.

        *cmd* overrides the default platform shell (useful for tool-spawned
        sessions that need a specific interpreter).
        """
        shell_cmd = cmd if cmd is not None else resolve_shell()
        proc = PtyProcess(shell_cmd, rows=rows, cols=cols, cwd=cwd)
        session_id = str(uuid.uuid4())
        session = TerminalSession(
            id=session_id,
            process=proc,
            name=name,
            cwd=cwd or "",
        )
        with self._lock:
            self._sessions[session_id] = session
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
