"""Cross-platform discovery and killing of slbp server-stack processes.

Backs `slbp process-doctor` -- a manual, last-resort tool for finding and
cleaning up orphaned ui/proxy/flask processes that a normal "Restart Server"
(pid-based, .slbp-server.json) failed to reach. See project memory on the
desktop server restart/EADDRINUSE investigation for the failure mode this
exists to work around: on Windows, a detached child (proxy-server especially,
since it's the only one with a fixed preferred port) can outlive its recorded
parent pid across a sleep/wake or a restart-on-top-of-a-stale-pid, leaving no
trace anywhere that still points to it.

Matching is done on specific, real command-line shapes verified against a
live install -- never a bare repo-path substring, which also catches
unrelated tooling that happens to run from the same venv (e.g. VS Code's
Python LSP servers) and Electron's own renderer/gpu/utility child processes.

Each hop in both the "server run" wrapper chain and the flask launcher chain
re-execs with its own full argv (Git Bash's `exec` does not preserve the OS
pid on Windows -- verified empirically, it spawns a new process), so every
hop is independently matchable this way. No parent/child tree-walking is
needed for discovery; ppid is only carried along for display grouping.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import psutil

ROLE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("server-run", re.compile(r"[\\/]slbp\s+server\s+run|main\.py\s+server\s+run")),
    ("ui", re.compile(r"[\\/]ui[\\/]serve\.cjs")),
    ("proxy", re.compile(r"[\\/]proxy-server[\\/]index\.js")),
    ("flask-launcher", re.compile(r"[\\/]run_ui_connector\.sh")),
    ("flask", re.compile(r"[\\/]ui_connector[\\/]main\.py")),
)


@dataclass
class MatchedProcess:
    pid: int
    ppid: int | None
    role: str
    create_time: float
    cmdline: str
    ports: list[int]

    @property
    def uptime_str(self) -> str:
        seconds = max(0, int(time.time() - self.create_time))
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h{minutes}m"
        if minutes:
            return f"{minutes}m{secs}s"
        return f"{secs}s"


def _role_for_cmdline(cmdline: str) -> str | None:
    for role, pattern in ROLE_PATTERNS:
        if pattern.search(cmdline):
            return role
    return None


def find_slbp_processes() -> list[MatchedProcess]:
    """Return every live process matching a known slbp server-stack role, oldest first."""
    self_pid = os.getpid()
    results: list[MatchedProcess] = []
    for proc in psutil.process_iter(["pid", "ppid", "cmdline", "create_time"]):
        try:
            info = proc.info
            if info["pid"] == self_pid:
                continue
            cmdline = " ".join(info.get("cmdline") or [])
            if not cmdline:
                continue
            role = _role_for_cmdline(cmdline)
            if role is None:
                continue

            ports: list[int] = []
            try:
                for conn in proc.net_connections(kind="inet"):
                    if conn.status == psutil.CONN_LISTEN and conn.laddr:
                        ports.append(conn.laddr.port)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            results.append(
                MatchedProcess(
                    pid=info["pid"],
                    ppid=info.get("ppid"),
                    role=role,
                    create_time=info["create_time"],
                    cmdline=cmdline,
                    ports=sorted(set(ports)),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    results.sort(key=lambda m: m.create_time)
    return results


def kill_process(pid: int) -> tuple[bool, str]:
    """Forcefully kill one process by pid. Returns (success, message)."""
    try:
        proc = psutil.Process(pid)
        proc.kill()
        proc.wait(timeout=5)
        return True, f"Killed PID {pid}."
    except psutil.NoSuchProcess:
        return True, f"PID {pid} was already gone."
    except psutil.TimeoutExpired:
        return False, f"PID {pid} did not exit within 5s of being killed."
    except psutil.AccessDenied:
        return False, f"Access denied killing PID {pid} (try an elevated/admin shell)."
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"Failed to kill PID {pid}: {exc}"
