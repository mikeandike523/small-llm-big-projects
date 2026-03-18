"""
Read/write .slbp-server.json in the project root.

This file stores runtime port assignments so that `slbp ui open` can discover
the URL without needing the ports to be predetermined.
"""

from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _PROJECT_ROOT / ".slbp-server.json"


def write_state(flask_port: int, ui_port: int, logging_port: int) -> None:
    """Write port assignments to .slbp-server.json."""
    _STATE_FILE.write_text(
        json.dumps(
            {
                "flask_port": flask_port,
                "ui_port": ui_port,
                "logging_port": logging_port,
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
