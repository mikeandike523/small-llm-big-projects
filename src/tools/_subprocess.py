from __future__ import annotations
import subprocess
import threading
import time
from dataclasses import dataclass

from src.utils.exceptions import ToolTimeoutError


@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    success: bool

    def __str__(self):
        parts = [
            "SUCCESS" if self.success else "ERROR",
            f"EXIT CODE: {self.returncode}" if not self.success else None,
            "STDOUT:\n\n"+self.stdout if self.stdout else None,
            "STDERR:\n\n"+self.stderr if self.stderr else None
              ]
        return "\n\n".join(filter(lambda x: (x or '').strip(), parts)).strip()


def run_command(
    cmd: list[str],
    timeout: int | None = None,
    cancel_event: threading.Event | None = None,
) -> SubprocessResult:
    """
    Run a command synchronously. Supports cancellation via cancel_event.

    Drains stdout/stderr in background threads to avoid pipe-buffer deadlock.
    Polls every 100ms so cancel_event is checked promptly.
    Raises ToolTimeoutError on timeout or cancellation.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    # Drain pipes in background threads to prevent deadlock when output is large.
    t_out = threading.Thread(
        target=lambda: stdout_chunks.append(proc.stdout.read() if proc.stdout else ""),
        daemon=True,
    )
    t_err = threading.Thread(
        target=lambda: stderr_chunks.append(proc.stderr.read() if proc.stderr else ""),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    poll_interval = 0.1
    elapsed = 0.0

    try:
        while proc.poll() is None:
            time.sleep(poll_interval)
            elapsed += poll_interval
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                t_out.join(timeout=2)
                t_err.join(timeout=2)
                raise ToolTimeoutError(
                    cmd[0] if cmd else "command",
                    int(elapsed),
                    hint="cancelled by user",
                    prior_stdout="".join(stdout_chunks) or None,
                    prior_stderr="".join(stderr_chunks) or None,
                )
            if timeout is not None and elapsed >= timeout:
                proc.kill()
                t_out.join(timeout=2)
                t_err.join(timeout=2)
                raise ToolTimeoutError(
                    cmd[0] if cmd else "command",
                    timeout,
                    prior_stdout="".join(stdout_chunks) or None,
                    prior_stderr="".join(stderr_chunks) or None,
                )
    finally:
        t_out.join(timeout=5)
        t_err.join(timeout=5)

    return SubprocessResult(
        returncode=proc.returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        success=proc.returncode == 0,
    )
