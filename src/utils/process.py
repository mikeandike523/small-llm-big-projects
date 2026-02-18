"""
Helpers for running multiple long-lived subprocesses concurrently, forwarding
their stdout/stderr to the current terminal in real time.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class ManagedProcess:
    label: str
    cmd: Sequence[str]
    cwd: str | Path | None = None


def _stream_output(proc: subprocess.Popen, label: str) -> None:
    """Read lines from proc.stdout and write them to sys.stdout with a prefix."""
    assert proc.stdout is not None
    for raw_line in iter(proc.stdout.readline, b""):
        line = raw_line.decode(errors="replace").rstrip("\n")
        sys.stdout.write(f"[{label}] {line}\n")
        sys.stdout.flush()
    proc.stdout.close()


def run_processes(processes: list[ManagedProcess]) -> None:
    """
    Start each process, forward all output to stdout prefixed with the process
    label, then block until all processes exit.

    Sends SIGTERM to all children on KeyboardInterrupt, waits for them to
    finish, then re-raises so the CLI can exit cleanly.
    """
    procs: list[subprocess.Popen] = []
    threads: list[threading.Thread] = []

    for mp in processes:
        proc = subprocess.Popen(
            mp.cmd,
            cwd=mp.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr into stdout
            bufsize=0,                 # unbuffered — get lines as they arrive
        )
        procs.append(proc)

        t = threading.Thread(
            target=_stream_output,
            args=(proc, mp.label),
            daemon=True,
        )
        t.start()
        threads.append(t)

    try:
        for proc in procs:
            proc.wait()
    except KeyboardInterrupt:
        print("\n[slbp] Shutting down all processes…", file=sys.stderr)
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise


def find_bash() -> str:
    """
    Return the path to a bash executable suitable for running .sh scripts.
    Prefers Git Bash on Windows; falls back to whatever 'bash' is in PATH.
    """
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate

    bash = shutil.which("bash")
    if bash:
        return bash

    raise RuntimeError(
        "Could not find bash.  Install Git for Windows or ensure bash is on PATH."
    )
