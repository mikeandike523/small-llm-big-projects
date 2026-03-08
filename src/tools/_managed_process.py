from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

from src.tools._subprocess import SubprocessResult
from src.tools._autoresponse import AutoResponse, find_response
from src.utils.exceptions import ToolHangError
from src.utils.log import log


# How often the watchdog wakes to flush partial output and check autoresponses.
# This also sets the latency before a non-newline-terminated prompt is flushed
# to the GUI (one READ_INTERVAL after the pipe goes idle).
READ_INTERVAL = 0.05  # seconds

# How long the stdout pipe must be idle (no new data) before an autoresponse
# is triggered. Must be >= READ_INTERVAL. Should be long enough that the
# process has finished writing the full prompt before we respond.
WAIT_UNTIL_RESPONSE = 0.3  # seconds

# Maximum time (seconds) the LLM is allowed to respond during hang triage.
# If the LLM exceeds this, treat the process as hung (no decision = hang).
HANG_DECISION_TIMEOUT = 10  # seconds


def _llm_triage(
    proc: subprocess.Popen,
    auto_buffer: list[str],
    last_data_time: list[float],
    hung_flag: list[bool],
) -> bool:
    """
    Out-of-band LLM triage called when idle >= hang_timeout.

    Stage 1: ask if the process is still computing or waiting for input.
    Stage 2 (only if waiting): ask what keys to press; inject them if simple.

    Returns True  -> extended the hang timer (caller should keep watching).
    Returns False -> decided to kill (hung_flag set, proc killed, caller breaks).
    """
    from src.utils.llm.factory import make_llm

    llm = make_llm(timeout_s=HANG_DECISION_TIMEOUT)
    if llm is None:
        # No LLM config available — fall back to original kill behaviour.
        hung_flag[0] = True
        proc.kill()
        return False

    buffer_snapshot = auto_buffer[0]

    # ------------------------------------------------------------------
    # Stage 1 — still processing, or waiting for input?
    # ------------------------------------------------------------------
    stage1_system = (
        "Your job is to determine if the CLI output shown represents a process "
        "that needs more time to complete, or a process that is waiting for human "
        "input. Respond with exactly one word: PROCESSING or INPUT."
    )
    try:
        r1 = llm.fetch([
            {"role": "system", "content": stage1_system},
            {"role": "user", "content": buffer_snapshot or "(no output yet)"},
        ], max_tokens=16)
        decision1 = r1.content.strip().upper()
    except Exception as exc:
        log(f"[hang-triage] Stage 1 LLM error: {exc} — treating as hung")
        hung_flag[0] = True
        proc.kill()
        return False

    if "PROCESSING" in decision1:
        log(f"[hang-triage] Stage 1: PROCESSING — extending hang timer")
        last_data_time[0] = time.monotonic()
        return True

    # ------------------------------------------------------------------
    # Stage 2 — what keys are needed?
    # ------------------------------------------------------------------
    stage2_system = (
        "A CLI process is waiting for input and the user has already pre-approved "
        "this action. What key(s) would you press to proceed? "
        "If only simple printable characters or Enter are needed (e.g. 'y', 'n', Enter), "
        "respond with SIMPLE: followed by the exact characters to send (use \\n for Enter). "
        "If the prompt requires arrow keys, function keys, Ctrl sequences, or interactive "
        "menu navigation, respond with EXOTIC."
    )
    try:
        r2 = llm.fetch([
            {"role": "system", "content": stage2_system},
            {"role": "user", "content": buffer_snapshot or "(no output yet)"},
        ], max_tokens=32)
        decision2 = r2.content.strip()
    except Exception as exc:
        log(f"[hang-triage] Stage 2 LLM error: {exc} — treating as hung")
        hung_flag[0] = True
        proc.kill()
        return False

    if decision2.upper().startswith("SIMPLE:"):
        keys_raw = decision2[len("SIMPLE:"):].strip()
        # Unescape \n so the LLM can express Enter literally.
        keys = keys_raw.replace("\\n", "\n")
        log(f"[hang-triage] Stage 2: SIMPLE keys={keys!r} — injecting and extending timer")
        try:
            proc.stdin.write(keys.encode())  # type: ignore[union-attr]
            proc.stdin.flush()              # type: ignore[union-attr]
        except Exception as exc:
            log(f"[hang-triage] stdin write failed: {exc} — treating as hung")
            hung_flag[0] = True
            proc.kill()
            return False
        auto_buffer[0] = ""
        last_data_time[0] = time.monotonic()
        return True

    # EXOTIC or unrecognised response — kill.
    log(f"[hang-triage] Stage 2: {decision2!r} — treating as hung")
    hung_flag[0] = True
    proc.kill()
    return False


def run_command_streaming(
    cmd: list[str],
    timeout: int | None,
    on_chunk: Callable[[str], None],
    autoresponses: list[AutoResponse] | None = None,
    hang_timeout: int | None = None,
) -> SubprocessResult:
    """
    Run a command and stream its output via on_chunk as it arrives.

    Uses 128-byte chunk reads (raw, unbuffered) so that partial lines —
    such as interactive prompts that don't end with a newline — are flushed
    to the caller promptly after READ_INTERVAL seconds of pipe silence.

    Complete lines (ending with '\\n') are emitted immediately as they arrive.
    Incomplete tail data is held until READ_INTERVAL of idle, then flushed.

    stderr chunks are prefixed with '[stderr] ' and emitted as they arrive.

    stdin is always opened as a pipe so both the static autoresponse rules and
    the LLM-based hang triage (Stage 2) can inject key responses.

    When autoresponses is non-empty:
      - A dedicated autoresponse buffer accumulates all stdout since the last
        triggered response (cleared on each match so pattern matching always
        sees only fresh, relevant data).
      - After WAIT_UNTIL_RESPONSE seconds of idle, the buffer is checked
        against the rule list; the first matching rule's response is written
        to stdin and the buffer is reset.

    Raises subprocess.TimeoutExpired if the overall timeout is exceeded.
    """
    use_auto = bool(autoresponses)

    # Always open stdin as a pipe so the LLM-based hang triage (Stage 2) can
    # inject key responses even when no static autoresponses are configured.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
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

    # Tracks whether we've already checked the current idle period for autoresponse
    # (to avoid calling find_response every 50ms on the same buffer with no match).
    auto_checked_at: list[float] = [-1.0]

    reader_done = threading.Event()
    hung_flag: list[bool] = [False]

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
            #    Only fire once per idle period — skip if the buffer hasn't changed
            #    since the last check (avoids calling find_response every 50ms on no-match).
            if use_auto and current_auto and idle >= WAIT_UNTIL_RESPONSE:
                checked_at = auto_checked_at[0]
                if checked_at != last_data_time[0]:
                    auto_checked_at[0] = last_data_time[0]
                    log(f"Current auto: "+current_auto)
                    response = find_response(current_auto, autoresponses)  # type: ignore[arg-type]

                    if response is not None:
                        with lock:
                            auto_buffer[0] = ""
                            last_data_time[0] = time.monotonic()  # reset idle timer
                            auto_checked_at[0] = -1.0  # allow rechecking after new data
                        try:
                            proc.stdin.write(response.encode())  # type: ignore[union-attr]
                            proc.stdin.flush()  # type: ignore[union-attr]
                        except Exception:
                            pass

            # 3. Hang detection with LLM triage.
            #    When idle exceeds hang_timeout and the process is still alive,
            #    ask the LLM whether this is a long-running process that needs
            #    more time, or an interactive prompt waiting for input.
            if hang_timeout is not None and idle >= hang_timeout:
                if proc.poll() is None:  # only flag as hung if process hasn't already exited
                    if not _llm_triage(proc, auto_buffer, last_data_time, hung_flag):
                        break  # triage decided to kill — watchdog exits
                    # triage extended the timer — continue the loop
                else:
                    break  # process already exited naturally

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

    # Use timeouts on joins: on Windows, orphaned child processes can keep the pipe
    # open after the parent is killed, causing read() to block indefinitely.
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    t_watch.join(timeout=5)

    try:
        proc.stdin.close()  # type: ignore[union-attr]
    except Exception:
        pass

    if hung_flag[0]:
        raise ToolHangError("host_shell", hang_timeout)  # type: ignore[arg-type]

    return SubprocessResult(
        returncode=proc.returncode,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        success=proc.returncode == 0,
    )
