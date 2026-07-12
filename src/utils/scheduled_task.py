"""
Cleanup helpers for the (now-removed) Windows Scheduled Task that used to run
`slbp server run` at user logon.

Only the bits `slbp server task purge` needs survive here: checking whether
the task is still registered, stopping it, and unregistering it. The desktop
app now owns starting the server (see desktop/src/main/serverLauncher.ts),
so nothing here creates or manages a task anymore.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

TASK_NAME = "SLBP Server"
SUPPORT_DIR = PROJECT_ROOT / ".slbp-task"


def task_exists() -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True,
    )
    return r.returncode == 0


def end_task() -> None:
    """Stop any currently running instance of the task, if one exists."""
    subprocess.run(
        ["schtasks", "/End", "/TN", TASK_NAME],
        capture_output=True,
        text=True,
    )


def delete_task() -> None:
    """Stop any running instance, then unregister the scheduled task."""
    end_task()
    r = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"schtasks /Delete failed: {r.stderr.strip() or r.stdout.strip()}"
        )
