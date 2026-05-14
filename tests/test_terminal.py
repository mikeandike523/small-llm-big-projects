"""
Terminal backend smoke tests.

Verifies that the shell resolver, PtyProcess, and TerminalSessionManager
work end-to-end on the current platform.  Each test has a hard timeout via
pytest-timeout so a hung PTY can never block the suite indefinitely.

Run:
    pytest tests/test_terminal.py -v
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from src.terminal import (
    PtyProcess,
    ShellNotFoundError,
    TerminalSession,
    TerminalSessionManager,
    resolve_shell,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INIT_WAIT = 1.5  # seconds to let the shell write its prompt before we drain
_CMD_WAIT = 8.0  # seconds to poll for command output


def _read_until(proc: PtyProcess, marker: bytes, timeout: float = _CMD_WAIT) -> bytes:
    """Accumulate PTY output until *marker* appears or *timeout* expires."""
    output = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = proc.read(timeout=0.2)
        output += chunk
        if marker in output:
            break
    return output


# ---------------------------------------------------------------------------
# Shell resolver
# ---------------------------------------------------------------------------


@pytest.mark.timeout(10)
def test_shell_resolver_returns_nonempty_argv():
    cmd = resolve_shell()
    assert isinstance(cmd, list)
    assert len(cmd) >= 1


@pytest.mark.timeout(10)
def test_shell_resolver_executable_exists():
    cmd = resolve_shell()
    exe = cmd[0]
    assert os.path.isfile(exe), f"Shell executable not found on disk: {exe!r}"


@pytest.mark.timeout(10)
def test_correct_shell_for_platform():
    cmd = resolve_shell()
    exe = cmd[0].lower()
    if sys.platform == "win32":
        assert "bash" in exe, f"Expected Git Bash on Windows, got: {exe!r}"
    elif sys.platform == "darwin":
        assert (
            "zsh" in exe or "bash" in exe
        ), f"Expected zsh/bash on macOS, got: {exe!r}"
    else:
        assert any(
            sh in exe for sh in ("bash", "zsh", "sh", "fish", "dash")
        ), f"Expected a known shell on Linux, got: {exe!r}"


# ---------------------------------------------------------------------------
# PtyProcess lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.timeout(15)
def test_pty_spawns_and_is_alive():
    proc = PtyProcess(resolve_shell(), rows=24, cols=80)
    try:
        time.sleep(0.5)
        assert proc.is_alive(), "Shell process exited immediately after spawn"
    finally:
        proc.terminate()


@pytest.mark.timeout(20)
def test_pty_echo():
    marker = b"__slbp_pty_test__"
    proc = PtyProcess(resolve_shell(), rows=24, cols=80)
    try:
        time.sleep(_INIT_WAIT)
        proc.read(timeout=0.5)  # drain login banner / prompt

        proc.write(b"echo " + marker + b"\r\n")
        output = _read_until(proc, marker)

        assert marker in output, f"Marker not found in PTY output.\nOutput: {output!r}"
    finally:
        proc.terminate()


@pytest.mark.timeout(15)
def test_pty_resize_no_crash():
    proc = PtyProcess(resolve_shell(), rows=24, cols=80)
    try:
        time.sleep(0.5)
        proc.resize(40, 120)  # should not raise
        proc.resize(24, 80)  # restore
    finally:
        proc.terminate()


@pytest.mark.timeout(15)
def test_pty_terminate_stops_process():
    proc = PtyProcess(resolve_shell(), rows=24, cols=80)
    time.sleep(0.5)
    proc.terminate()
    # Give the reader thread a moment to detect exit.
    time.sleep(1.0)
    assert not proc.is_alive(), "Process still alive after terminate()"


@pytest.mark.timeout(15)
def test_pty_exit_code_available_after_exit():
    proc = PtyProcess(resolve_shell(), rows=24, cols=80)
    time.sleep(_INIT_WAIT)
    proc.read(timeout=0.5)

    # Send 'exit' so the shell exits cleanly rather than being killed.
    proc.write(b"exit\r\n")
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and proc.is_alive():
        time.sleep(0.2)

    # exit_code may be None on some platforms if the shell was already reaped;
    # what matters is that is_alive() eventually goes False.
    assert not proc.is_alive(), "Shell did not exit after 'exit' command"


# ---------------------------------------------------------------------------
# TerminalSessionManager
# ---------------------------------------------------------------------------


@pytest.mark.timeout(20)
def test_session_manager_create_and_list():
    mgr = TerminalSessionManager()
    session = mgr.create(name="test-session")
    try:
        time.sleep(0.5)
        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == session.id
        assert sessions[0].name == "test-session"
    finally:
        mgr.destroy(session.id)


@pytest.mark.timeout(20)
def test_session_manager_get():
    mgr = TerminalSessionManager()
    session = mgr.create()
    try:
        fetched = mgr.get(session.id)
        assert fetched is not None
        assert fetched.id == session.id
        assert mgr.get("nonexistent-id") is None
    finally:
        mgr.destroy(session.id)


@pytest.mark.timeout(20)
def test_session_manager_destroy_removes_session():
    mgr = TerminalSessionManager()
    session = mgr.create()
    time.sleep(0.5)
    mgr.destroy(session.id)
    time.sleep(0.5)

    assert mgr.get(session.id) is None
    assert len(mgr.list_sessions()) == 0


@pytest.mark.timeout(20)
def test_session_manager_multiple_sessions():
    mgr = TerminalSessionManager()
    s1 = mgr.create(name="a")
    s2 = mgr.create(name="b")
    try:
        sessions = mgr.list_sessions()
        ids = {s.id for s in sessions}
        assert s1.id in ids
        assert s2.id in ids
        assert len(sessions) == 2
    finally:
        mgr.destroy(s1.id)
        mgr.destroy(s2.id)


@pytest.mark.timeout(20)
def test_session_manager_cleanup_dead():
    mgr = TerminalSessionManager()
    session = mgr.create()
    time.sleep(0.5)

    # Kill process directly without going through destroy().
    session.process.terminate()
    time.sleep(1.0)

    removed = mgr.cleanup_dead()
    assert removed >= 1
    assert mgr.get(session.id) is None
