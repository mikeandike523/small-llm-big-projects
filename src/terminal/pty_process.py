from __future__ import annotations

import queue
import sys
import threading
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# Platform-specific imports
# ---------------------------------------------------------------------------
# On Windows we use pywinpty (ConPTY via CreatePseudoConsole + CreateProcess).
# On Unix/macOS we use ptyprocess (POSIX openpty + fork/exec).
# Both expose nearly identical APIs; the wrapper below normalises the
# differences (read/write bytes vs str, exception types).

if sys.platform == "win32":
    import winpty as _backend  # pywinpty
    _BackendClass = _backend.PtyProcess
else:
    import ptyprocess as _backend  # ptyprocess
    _BackendClass = _backend.PtyProcess  # bytes I/O


class PtyProcess:
    """
    Cross-platform pseudo-terminal process.

    All I/O is bytes.  ANSI escape sequences produced by the child shell are
    passed through unchanged so the client (xterm.js) can interpret them.
    """

    def __init__(
        self,
        cmd: list[str],
        rows: int = 24,
        cols: int = 80,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._output_queue: queue.Queue[bytes] = queue.Queue()
        self._exit_code: int | None = None

        self._proc = _BackendClass.spawn(
            cmd,
            dimensions=(rows, cols),
            cwd=cwd,
            env=env,
        )

        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()

    # ------------------------------------------------------------------
    # Background reader — drains the PTY master fd into the output queue
    # ------------------------------------------------------------------

    def _reader(self) -> None:
        while True:
            try:
                chunk = self._proc.read(4096)
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                if chunk:
                    self._output_queue.put(chunk)
            except EOFError:
                break
            except Exception:
                break

        try:
            self._exit_code = self._proc.exitstatus
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, timeout: float = 0.05) -> bytes:
        """
        Return all buffered output bytes, blocking up to *timeout* seconds
        for the first chunk.  Subsequent chunks in the queue are collected
        without additional waiting so a burst of data is returned atomically.
        """
        chunks: list[bytes] = []
        try:
            chunks.append(self._output_queue.get(timeout=timeout))
            # Drain any further chunks that arrived in the same burst.
            while True:
                chunks.append(self._output_queue.get_nowait())
        except queue.Empty:
            pass
        return b"".join(chunks)

    def write(self, data: bytes) -> None:
        """Write raw bytes to the shell stdin."""
        if sys.platform == "win32":
            self._proc.write(data.decode("utf-8", errors="replace"))
        else:
            self._proc.write(data)

    def resize(self, rows: int, cols: int) -> None:
        """Notify the child process of a terminal resize."""
        self._proc.setwinsize(rows, cols)

    def terminate(self, force: bool = False) -> None:
        """Terminate the child process."""
        try:
            self._proc.terminate(force=force)
        except Exception:
            pass

    def is_alive(self) -> bool:
        """Return True if the child process is still running."""
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    @property
    def exit_code(self) -> int | None:
        """Exit status of the child, or None if still running."""
        return self._exit_code
