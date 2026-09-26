from __future__ import annotations
import subprocess
import threading
import time
from dataclasses import dataclass

from src.utils.exceptions import ToolTimeoutError
from src.tools._process_tree import isolated_process_kwargs, kill_process_tree


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
            "STDOUT:\n\n" + self.stdout if self.stdout else None,
            "STDERR:\n\n" + self.stderr if self.stderr else None,
        ]
        return "\n\n".join(filter(lambda x: (x or "").strip(), parts)).strip()


def run_command(
    cmd: list[str],
    timeout: int | None = None,
    cancel_event: threading.Event | None = None,
    cwd: str | None = None,
) -> SubprocessResult:
    """
    Run a command synchronously. Supports cancellation via cancel_event.

    Drains stdout/stderr in background threads to avoid pipe-buffer deadlock.
    Waits on cancel_event in 100ms windows, so cancellation wakes immediately
    while process completion and the monotonic deadline are checked frequently.
    Raises ToolTimeoutError on timeout or cancellation.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        **isolated_process_kwargs(),
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
    started_at = time.monotonic()

    try:
        while proc.poll() is None:
            cancelled = (
                cancel_event.wait(poll_interval)
                if cancel_event is not None
                else False
            )
            if cancel_event is None:
                time.sleep(poll_interval)
            elapsed = time.monotonic() - started_at
            if cancelled:
                kill_process_tree(proc)
                t_out.join(timeout=2)
                t_err.join(timeout=2)
                raise ToolTimeoutError(
                    cmd[0] if cmd else "command",
                    round(elapsed, 3),
                    hint="cancelled by user",
                    prior_stdout="".join(stdout_chunks) or None,
                    prior_stderr="".join(stderr_chunks) or None,
                )
            if timeout is not None and elapsed >= timeout:
                kill_process_tree(proc)
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
