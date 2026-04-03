from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

from termcolor import colored

from src.tools._subprocess import SubprocessResult
from src.tools._autoresponse import AutoResponse, find_response
from src.utils.exceptions import ToolHangError, ToolTimeoutError
from src.utils.log import log


# ---------------------------------------------------------------------------
# I/O polling constants
# ---------------------------------------------------------------------------

# How often the watchdog thread wakes to flush partial output and check
# autoresponses. This also controls how quickly a non-newline-terminated
# prompt appears in the GUI: it will be flushed one READ_INTERVAL after
# the pipe goes idle.
READ_INTERVAL = 0.05  # seconds

# How long stdout must be idle before an autoresponse rule is checked.
# Must be >= READ_INTERVAL. Give the process enough time to finish printing
# its full prompt before we fire a response.
WAIT_UNTIL_RESPONSE = 0.3  # seconds

# ---------------------------------------------------------------------------
# LLM hang-triage constants
# ---------------------------------------------------------------------------

# Maximum seconds the LLM is given to respond during any single triage call.
# Applies to both Stage 1 (WAITING/INPUT classification) and Stage 1b
# (dynamic extension estimate) and Stage 2 (key injection). If the LLM
# exceeds this budget, the call is treated as failed and we fall back or kill.
HANG_DECISION_TIMEOUT = 30  # seconds

# When Stage 1 returns WAITING, Stage 1b asks the LLM how long to wait before
# checking again. Its answer is clamped to [MIN_EXTENSION_WAIT, MAX_EXTENSION_WAIT].
# If the answer is outside this range, unparseable, or the LLM call fails, we
# fall back silently to the caller-supplied hang_timeout value.
#
# MIN_EXTENSION_WAIT: shortest extension the LLM may request. Prevents the
#   watchdog from polling more aggressively than this even if the LLM says so.
# MAX_EXTENSION_WAIT: longest single extension the LLM may request. Prevents
#   indefinite deferral — but note the overall command timeout is the true hard
#   cap; extensions simply control how often we re-check.
MIN_EXTENSION_WAIT = 15   # seconds
MAX_EXTENSION_WAIT = 180  # seconds


def _llm_triage(
    proc: subprocess.Popen,
    auto_buffer: list[str],
    last_data_time: list[float],
    hung_flag: list[bool],
    lock: threading.Lock,
    on_log: Callable[[str], None] | None,
    triage_count: list[int],
    hang_timeout: float,
    start_time: float,
) -> bool:
    """
    Out-of-band LLM triage called when idle >= hang_timeout.

    Stage 1:  Classify output as WAITING (still computing) or INPUT (waiting for key).
    Stage 1b: (WAITING path only) Ask LLM how many seconds to wait before next check.
              Clamped to [MIN_EXTENSION_WAIT, MAX_EXTENSION_WAIT]; falls back to
              hang_timeout on any error or out-of-range answer.
    Stage 2:  (INPUT path only) Ask what keys to send; inject if SIMPLE, kill if EXOTIC.

    The overall command timeout (proc.wait(timeout=...)) is the hard cap on total
    runtime — this function never needs to enforce a separate extensions limit.

    Returns True  -> extended the hang timer (caller should keep watching).
    Returns False -> decided to kill (hung_flag set, proc killed, caller breaks).
    """
    def _log(msg: str) -> None:
        log(f"[hang-triage] {msg}")
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass

    def _kill(reason: str) -> bool:
        _log(reason)
        hung_flag[0] = True
        proc.kill()
        # Close pipes immediately so the blocked read() in the reader threads
        # gets an exception and they exit without waiting for EOF.
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe and not pipe.closed:
                    pipe.close()
            except Exception:
                pass
        return False

    triage_count[0] += 1
    extension_num = triage_count[0]
    elapsed = time.monotonic() - start_time

    with lock:
        buffer_snapshot = auto_buffer[0]

    _log(colored(
        f"Hang triage extension #{extension_num} — total watched: {elapsed:.0f}s",
        "yellow",
    ))

    from src.utils.llm.factory import make_llm
    llm = make_llm(timeout_s=HANG_DECISION_TIMEOUT)
    if llm is None:
        return _kill(colored("No LLM available — killing process", "red"))

    # ------------------------------------------------------------------
    # Stage 1 — still processing (WAITING) or waiting for a key (INPUT)?
    # ------------------------------------------------------------------
    stage1_system = (
        "You are analyzing CLI output to determine why a process has gone idle.\n"
        "\n"
        "Classify the situation as exactly one of:\n"
        "  WAITING  - The process is actively working and needs more time "
        "(e.g. installing packages, downloading files, compiling, running tests, indexing).\n"
        "  INPUT    - The process has paused and is waiting for the user to type "
        "something or press a key (e.g. a yes/no prompt, a license agreement, a menu).\n"
        "\n"
        "Reply with exactly one word: WAITING or INPUT."
    )
    try:
        r1 = llm.fetch([
            {"role": "system", "content": stage1_system},
            {"role": "user", "content": buffer_snapshot or "(no output yet)"},
        ])
        decision1 = r1.content.strip().upper()
    except Exception as exc:
        return _kill(colored(f"LLM error in stage 1: {exc} — killing process", "red"))

    if "WAITING" in decision1:
        # ------------------------------------------------------------------
        # Stage 1b — how many seconds to wait before the next triage check?
        # An independent LLM call; any failure falls back to hang_timeout.
        # ------------------------------------------------------------------
        stage1b_system = (
            "A CLI process is actively working (e.g. installing packages, downloading, "
            "compiling, running tests) and has produced no new output for a short while.\n"
            "Based on the output so far, estimate how many more seconds to wait "
            "before checking on it again.\n"
            "\n"
            f"Reply with a single integer between {MIN_EXTENSION_WAIT} and {MAX_EXTENSION_WAIT}. "
            "Reply with the number only, nothing else."
        )
        chosen_wait = hang_timeout  # fallback if call fails or answer is invalid
        try:
            r1b = llm.fetch([
                {"role": "system", "content": stage1b_system},
                {"role": "user", "content": buffer_snapshot or "(no output yet)"},
            ])
            raw = r1b.content.strip()
            parsed = float(raw)
            if MIN_EXTENSION_WAIT <= parsed <= MAX_EXTENSION_WAIT:
                chosen_wait = parsed
                _log(colored(
                    f"Stage 1b: next check in {chosen_wait:.0f}s (LLM estimate)",
                    "cyan",
                ))
            else:
                _log(colored(
                    f"Stage 1b: LLM returned {parsed:.0f}s which is outside "
                    f"[{MIN_EXTENSION_WAIT}, {MAX_EXTENSION_WAIT}] "
                    f"— falling back to {hang_timeout:.0f}s",
                    "yellow",
                ))
        except Exception as exc:
            _log(colored(
                f"Stage 1b: LLM error ({exc}) — falling back to {hang_timeout:.0f}s",
                "yellow",
            ))

        # Advance last_data_time so the next triage fires in chosen_wait seconds.
        # The watchdog triggers when (now - last_data_time) >= hang_timeout, so:
        #   last_data_time = now - hang_timeout + chosen_wait
        # gives exactly chosen_wait seconds until next triage.
        with lock:
            last_data_time[0] = time.monotonic() - hang_timeout + chosen_wait
        return True

    _log(colored("Stage 1: INPUT — process is waiting for a key response", "yellow"))

    # ------------------------------------------------------------------
    # Stage 2 — what keys are needed?
    # ------------------------------------------------------------------
    stage2_system = (
        "A CLI process is waiting for user input. The user has already approved running this command.\n"
        "What key(s) should be sent to proceed?\n"
        "\n"
        "If only simple printable characters or Enter are needed (e.g. 'y', 'n', Enter to confirm), reply:\n"
        "  SIMPLE: <characters>   (use \\n for Enter)\n"
        "\n"
        "If the prompt requires arrow keys, Escape, function keys, Ctrl sequences, or interactive "
        "menu navigation, reply:\n"
        "  EXOTIC\n"
        "\n"
        "Reply with either SIMPLE:<chars> or EXOTIC."
    )
    try:
        r2 = llm.fetch([
            {"role": "system", "content": stage2_system},
            {"role": "user", "content": buffer_snapshot or "(no output yet)"},
        ])
        decision2 = r2.content.strip()
    except Exception as exc:
        return _kill(colored(f"LLM error in stage 2: {exc} — killing process", "red"))

    if decision2.upper().startswith("SIMPLE:"):
        keys_raw = decision2[len("SIMPLE:"):].strip()
        # Unescape \n so the LLM can express Enter literally.
        keys = keys_raw.replace("\\n", "\n")
        _log(colored(f"Stage 2: SIMPLE keys={keys!r} — injecting and extending timer", "cyan"))
        try:
            proc.stdin.write(keys.encode())  # type: ignore[union-attr]
            proc.stdin.flush()              # type: ignore[union-attr]
        except Exception as exc:
            return _kill(colored(f"stdin write failed: {exc} — killing process", "red"))
        with lock:
            auto_buffer[0] = ""
            last_data_time[0] = time.monotonic()
        return True

    return _kill(colored(f"Stage 2: {decision2!r} (EXOTIC) — killing process", "red"))


def run_command_streaming(
    cmd: list[str],
    timeout: int | None,
    on_chunk: Callable[[str], None],
    autoresponses: list[AutoResponse] | None = None,
    hang_timeout: int | None = None,
    on_log: Callable[[str], None] | None = None,
    tool_name: str = "host_shell",
    timeout_hint: str | None = None,
    cancel_event: threading.Event | None = None,
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

    The overall timeout is enforced by proc.wait(timeout=timeout) on the main
    thread. This is the hard cap — the watchdog triage loop runs independently
    and can grant as many extensions as it likes within that window.

    Raises subprocess.TimeoutExpired if the overall timeout is exceeded.
    Raises ToolHangError if hang_timeout elapses with no output and LLM triage
    decides to kill the process.
    """
    use_auto = bool(autoresponses)

    # Record wall-clock start so triage can report total watched time.
    start_time = time.monotonic()

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

    # Simple counter for labelling triage log messages (extension #N).
    triage_count: list[int] = [0]

    # ------------------------------------------------------------------
    # stdout reader: 128-byte chunks, raw binary, decode UTF-8.
    # on_chunk calls are made OUTSIDE the lock to avoid blocking the
    # watchdog while I/O is in flight.
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
            lines_to_emit: list[str] = []
            with lock:
                last_data_time[0] = time.monotonic()
                stdout_parts.append(text)
                tail_buffer[0] += text
                auto_buffer[0] += text

                # Collect complete lines while holding the lock; emit outside.
                while "\n" in tail_buffer[0]:
                    line, tail_buffer[0] = tail_buffer[0].split("\n", 1)
                    lines_to_emit.append(line + "\n")

            for line in lines_to_emit:
                try:
                    on_chunk(line)
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
    #   3. Run LLM triage after idle >= hang_timeout
    #
    # Note: the watchdog runs until reader_done is set (stdout EOF) or it
    # decides to kill the process. The hard runtime cap is proc.wait() on
    # the main thread, which kills the process on overall timeout regardless
    # of what the watchdog is doing.
    # ------------------------------------------------------------------
    def _watchdog() -> None:
        while not reader_done.wait(timeout=READ_INTERVAL):
            # Cancel check: honour external cancellation immediately.
            if cancel_event is not None and cancel_event.is_set():
                if proc.poll() is None:
                    proc.kill()
                    for pipe in (proc.stdout, proc.stderr):
                        try:
                            if pipe and not pipe.closed:
                                pipe.close()
                        except Exception:
                            pass
                hung_flag[0] = True
                break

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
            #    ask the LLM whether to wait longer or kill.
            #    No extensions cap here — the overall command timeout is the hard limit.
            if hang_timeout is not None and idle >= hang_timeout:
                if proc.poll() is None:  # only triage if process hasn't already exited
                    if not _llm_triage(
                        proc, auto_buffer, last_data_time, hung_flag,
                        lock, on_log, triage_count,
                        hang_timeout=hang_timeout,
                        start_time=start_time,
                    ):
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
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe and not pipe.closed:
                    pipe.close()
            except Exception:
                pass
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        t_watch.join(timeout=2)
        raise ToolTimeoutError(
            tool_name,
            timeout,
            hint=timeout_hint,
            prior_stdout="".join(stdout_parts) or None,
            prior_stderr="".join(stderr_parts) or None,
        )

    # Use timeouts on joins: on Windows, orphaned child processes can keep the pipe
    # open after the parent is killed, causing read() to block indefinitely.
    # Watchdog timeout must cover an in-flight triage call: Stage 1 + Stage 1b each
    # cost up to HANG_DECISION_TIMEOUT, so allow 2x plus a small buffer.
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    t_watch.join(timeout=max(5, HANG_DECISION_TIMEOUT * 2 + 5))

    try:
        proc.stdin.close()  # type: ignore[union-attr]
    except Exception:
        pass

    if hung_flag[0]:
        raise ToolHangError(
            tool_name,
            hang_timeout,  # type: ignore[arg-type]
            prior_stdout="".join(stdout_parts) or None,
            prior_stderr="".join(stderr_parts) or None,
        )

    return SubprocessResult(
        returncode=proc.returncode,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        success=proc.returncode == 0,
    )
