import subprocess
import threading
import time
from typing import Callable

from termcolor import colored

from src.tools._managed_process_shared_defs import (
    MAX_EXTENSION_WAIT,
    MIN_EXTENSION_WAIT,
    logger,
    HANG_DECISION_TIMEOUT,
)


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
    on_usage=None,
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
        logger.info("[hang-triage] %s", msg)
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

    _log(
        colored(
            f"Hang triage extension #{extension_num} — total watched: {elapsed:.0f}s",
            "yellow",
        )
    )

    from src.utils.llm.factory import make_llm, load_llm_config, _call_sampler

    llm = make_llm(timeout_s=HANG_DECISION_TIMEOUT)
    if llm is None:
        return _kill(colored("No LLM available — killing process", "red"))
    _llm_cfg = load_llm_config() or {}
    _watchdog_params: dict = _llm_cfg.get("watchdog_params") or {}

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
        r1 = _call_sampler(
            llm,
            [
                {"role": "system", "content": stage1_system},
                {"role": "user", "content": buffer_snapshot or "(no output yet)"},
            ],
            _watchdog_params,
            on_usage,
        )
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
            r1b = _call_sampler(
                llm,
                [
                    {"role": "system", "content": stage1b_system},
                    {"role": "user", "content": buffer_snapshot or "(no output yet)"},
                ],
                _watchdog_params,
                on_usage,
            )
            raw = r1b.content.strip()
            parsed = float(raw)
            if MIN_EXTENSION_WAIT <= parsed <= MAX_EXTENSION_WAIT:
                chosen_wait = parsed
                _log(
                    colored(
                        f"Stage 1b: next check in {chosen_wait:.0f}s (LLM estimate)",
                        "cyan",
                    )
                )
            else:
                _log(
                    colored(
                        f"Stage 1b: LLM returned {parsed:.0f}s which is outside "
                        f"[{MIN_EXTENSION_WAIT}, {MAX_EXTENSION_WAIT}] "
                        f"— falling back to {hang_timeout:.0f}s",
                        "yellow",
                    )
                )
        except Exception as exc:
            _log(
                colored(
                    f"Stage 1b: LLM error ({exc}) — falling back to {hang_timeout:.0f}s",
                    "yellow",
                )
            )

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
        r2 = _call_sampler(
            llm,
            [
                {"role": "system", "content": stage2_system},
                {"role": "user", "content": buffer_snapshot or "(no output yet)"},
            ],
            _watchdog_params,
            on_usage,
        )
        decision2 = r2.content.strip()
    except Exception as exc:
        return _kill(colored(f"LLM error in stage 2: {exc} — killing process", "red"))

    if decision2.upper().startswith("SIMPLE:"):
        keys_raw = decision2[len("SIMPLE:") :].strip()
        # Unescape \n so the LLM can express Enter literally.
        keys = keys_raw.replace("\\n", "\n")
        _log(
            colored(
                f"Stage 2: SIMPLE keys={keys!r} — injecting and extending timer", "cyan"
            )
        )
        try:
            proc.stdin.write(keys.encode())  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except Exception as exc:
            return _kill(colored(f"stdin write failed: {exc} — killing process", "red"))
        with lock:
            auto_buffer[0] = ""
            last_data_time[0] = time.monotonic()
        return True

    return _kill(colored(f"Stage 2: {decision2!r} (EXOTIC) — killing process", "red"))
