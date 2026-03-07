from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

from src.tools._subprocess import SubprocessResult
from src.tools._autoresponse import AutoResponse, find_response


# How often the watchdog wakes to flush partial output and check autoresponses.
# This also sets the latency before a non-newline-terminated prompt is flushed
# to the GUI (one READ_INTERVAL after the pipe goes idle).
READ_INTERVAL = 0.05  # seconds

# How long the stdout pipe must be idle (no new data) before an autoresponse
# is triggered. Must be >= READ_INTERVAL. Should be long enough that the
# process has finished writing the full prompt before we respond.
WAIT_UNTIL_RESPONSE = 0.3  # seconds


def run_command_streaming(
    cmd: list[str],
    timeout: int | None,
    on_chunk: Callable[[str], None],
    autoresponses: list[AutoResponse] | None = None,
) -> SubprocessResult:
    """
    Run a command and stream its output via on_chunk as it arrives.

    Uses 128-byte chunk reads (raw, unbuffered) so that partial lines —
    such as interactive prompts that don't end with a newline — are flushed
    to the caller promptly after READ_INTERVAL seconds of pipe silence.

    Complete lines (ending with '\\n') are emitted immediately as they arrive.
    Incomplete tail data is held until READ_INTERVAL of idle, then flushed.

    stderr chunks are prefixed with '[stderr] ' and emitted as they arrive.

    When autoresponses is non-empty:
      - stdin is opened as a pipe.
      - A dedicated autoresponse buffer accumulates all stdout since the last
        triggered response (cleared on each match so pattern matching always
        sees only fresh, relevant data).
      - After WAIT_UNTIL_RESPONSE seconds of idle, the buffer is checked
        against the rule list; the first matching rule's response is written
        to stdin and the buffer is reset.

    Raises subprocess.TimeoutExpired if the overall timeout is exceeded.
    """
    use_auto = bool(autoresponses)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if use_auto else None,
        bufsize=0,  # raw binary: read() returns immediately with available bytes
    )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    lock = threading.Lock()

    # Incomplete stdout tail (no trailing newline yet); flushed after idle.
    tail_buffer: list[str] = [""]

    # Accumulates all stdout since the last autoresponse match.
    # Cleared when a response is sent so the next prompt starts fresh.
    auto_buffer: list[str] = [""]

    # Monotonic timestamp of the last received stdout byte.
    last_data_time: list[float] = [time.monotonic()]

    reader_done = threading.Event()

    # ------------------------------------------------------------------
    # stdout reader: 128-byte chunks, raw binary, decode UTF-8
    # ------------------------------------------------------------------
    def _read_stdout() -> None:
        while True:
            try:
                chunk = proc.stdout.read(128)  # type: ignore[union-attr]
            except Exception:
                break
            if not chunk:
                break  # EOF

            text = chunk.decode("utf-8", errors="replace")
            with lock:
                last_data_time[0] = time.monotonic()
                stdout_parts.append(text)
                tail_buffer[0] += text
                auto_buffer[0] += text

                # Emit all complete lines immediately.
                while "\n" in tail_buffer[0]:
                    line, tail_buffer[0] = tail_buffer[0].split("\n", 1)
                    try:
                        on_chunk(line + "\n")
                    except Exception:
                        pass

        proc.stdout.close()  # type: ignore[union-attr]
        reader_done.set()

    # ------------------------------------------------------------------
    # stderr reader: larger chunks, no autoresponse needed
    # ------------------------------------------------------------------
    def _read_stderr() -> None:
        while True:
            try:
                chunk = proc.stderr.read(4096)  # type: ignore[union-attr]
            except Exception:
                break
            if not chunk:
                break  # EOF

            text = chunk.decode("utf-8", errors="replace")
            stderr_parts.append(text)
            try:
                on_chunk("[stderr] " + text)
            except Exception:
                pass

        proc.stderr.close()  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Watchdog: wakes every READ_INTERVAL to:
    #   1. Flush partial tail to GUI after idle >= READ_INTERVAL
    #   2. Trigger autoresponse after idle >= WAIT_UNTIL_RESPONSE
    # ------------------------------------------------------------------
    def _watchdog() -> None:
        while not reader_done.wait(timeout=READ_INTERVAL):
            now = time.monotonic()
            with lock:
                idle = now - last_data_time[0]
                current_tail = tail_buffer[0]
                current_auto = auto_buffer[0]

            # 1. Flush partial tail after one READ_INTERVAL of pipe silence.
            if current_tail and idle >= READ_INTERVAL:
                with lock:
                    # Re-check: only flush if the tail hasn't changed since we sampled it.
                    if tail_buffer[0] == current_tail:
                        tail_buffer[0] = ""
                        flushed = current_tail
                    else:
                        flushed = ""
                if flushed:
                    try:
                        on_chunk(flushed)
                    except Exception:
                        pass

            # 2. Autoresponse: check after WAIT_UNTIL_RESPONSE of idle.
            if use_auto and current_auto and idle >= WAIT_UNTIL_RESPONSE:
                response = find_response(current_auto, autoresponses)  # type: ignore[arg-type]
                if response is not None:
                    with lock:
                        auto_buffer[0] = ""
                        last_data_time[0] = time.monotonic()  # reset idle timer
                    try:
                        proc.stdin.write(response.encode())  # type: ignore[union-attr]
                        proc.stdin.flush()  # type: ignore[union-attr]
                    except Exception:
                        pass

        # Reader has finished — flush any remaining tail.
        with lock:
            remaining = tail_buffer[0]
            tail_buffer[0] = ""
        if remaining:
            try:
                on_chunk(remaining)
            except Exception:
                pass

    t_out = threading.Thread(target=_read_stdout, daemon=True)
    t_err = threading.Thread(target=_read_stderr, daemon=True)
    t_watch = threading.Thread(target=_watchdog, daemon=True)
    t_out.start()
    t_err.start()
    t_watch.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        t_watch.join(timeout=2)
        raise

    t_out.join()
    t_err.join()
    t_watch.join()

    if use_auto:
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass

    return SubprocessResult(
        returncode=proc.returncode,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        success=proc.returncode == 0,
    )
