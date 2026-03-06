from __future__ import annotations

import subprocess
import threading
from typing import Callable

from src.tools._subprocess import SubprocessResult


def run_command_streaming(
    cmd: list[str],
    timeout: int | None,
    on_chunk: Callable[[str], None],
) -> SubprocessResult:
    """
    Run a command and call on_chunk for each line of output as it arrives.
    stdout lines are passed as-is; stderr lines are prefixed with '[stderr] '.
    Returns a SubprocessResult with the full accumulated output.
    Raises subprocess.TimeoutExpired if the timeout is exceeded.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_lines.append(line)
            try:
                on_chunk(line)
            except Exception:
                pass
        proc.stdout.close()

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            try:
                on_chunk("[stderr] " + line)
            except Exception:
                pass
        proc.stderr.close()

    t_out = threading.Thread(target=_read_stdout, daemon=True)
    t_err = threading.Thread(target=_read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        raise

    t_out.join()
    t_err.join()

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    return SubprocessResult(
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        success=proc.returncode == 0,
    )
