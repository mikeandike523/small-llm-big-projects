"""
Read/write .slbp-server.json in the project root.

This file stores runtime port assignments so that `slbp ui open` can discover
the URL without needing the ports to be predetermined.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _PROJECT_ROOT / ".slbp-server.json"


def write_state(flask_port: int, ui_port: int, proxy_port: int) -> None:
    """Write port assignments (and this process's pid) to .slbp-server.json."""
    _STATE_FILE.write_text(
        json.dumps(
            {
                "proxy_port": proxy_port,
                "flask_port": flask_port,
                "ui_port": ui_port,
                "pid": os.getpid(),
            },
            indent=2,
        )
    )


def read_state() -> dict | None:
    """Return the state dict, or None if the file does not exist."""
    if not _STATE_FILE.exists():
        return None
    try:
        return json.loads(_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_state() -> None:
    """Remove the state file if it exists."""
    _STATE_FILE.unlink(missing_ok=True)


def get_running_server_state(timeout: float = 1.5, retries: int = 2) -> dict | None:
    """
    Return the state dict iff a server is actually reachable, else None.

    A present .slbp-server.json only means *some* run wrote it -- it's left
    behind by an unclean exit (e.g. taskkill) just as often as by a live
    server, so presence alone can't be trusted. This probes an existing
    backend route through the gateway to confirm the process is actually
    live before treating the recorded ports/pid as current.

    A false "not running" here is much costlier than a false "running" --
    the former can lead a caller to spawn a duplicate server stack, the
    latter just means a retry -- so a single slow/flaky probe isn't allowed
    to be the final word; retries only stop early on success.
    """
    state = read_state()
    if state is None:
        return None
    proxy_port = state.get("proxy_port")
    if not proxy_port:
        return None
    for _ in range(retries):
        try:
            r = httpx.get(
                f"http://127.0.0.1:{proxy_port}/api/session-defaults", timeout=timeout
            )
            if r.status_code == 200:
                return state
        except httpx.HTTPError:
            pass
    return None
