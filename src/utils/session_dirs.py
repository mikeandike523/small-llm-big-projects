"""Per-session folders under ``~/.slbp``.

Every session gets two folders keyed by its id:

- ``~/.slbp/workspaces/<session-id>`` -- the folder the New Session dialog
  suggests as the session's initial cwd. It has no special meaning to the
  agent; it is only created when a session actually starts inside it, and it
  is kept when the session is deleted (it holds the user's deliverables).
- ``~/.slbp/scratchpads/<session-id>`` -- disposable scratch space for the
  agent. Always created (and re-ensured whenever a session loads), approved
  like the session's cwd, and deleted with the session.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


def _slbp_home() -> Path:
    return Path.home() / ".slbp"


def get_session_workspaces_root() -> str:
    return _portable(_slbp_home() / "workspaces")


def get_session_scratchpads_root() -> str:
    return _portable(_slbp_home() / "scratchpads")


def get_session_workspace_dir(session_id: str) -> str:
    return _portable(_slbp_home() / "workspaces" / session_id)


def get_session_scratchpad_dir(session_id: str) -> str:
    return _portable(_slbp_home() / "scratchpads" / session_id)


def is_valid_session_id(value: object) -> bool:
    """True if *value* is a canonical lowercase UUID string (what uuid4() emits)."""
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _is_under_workspaces_root(path: str) -> bool:
    root = Path(get_session_workspaces_root()).resolve()
    try:
        Path(path).resolve().relative_to(root)
    except ValueError:
        return False
    return True


def ensure_session_dirs(session_id: str, initial_cwd: str | None) -> None:
    """Create the session's scratchpad, and its initial cwd when that cwd is
    a session workspace folder. Any other missing initial cwd is left alone --
    a deleted real project folder must not silently come back empty.

    Raises OSError if a folder cannot be created.
    """
    Path(get_session_scratchpad_dir(session_id)).mkdir(parents=True, exist_ok=True)
    if initial_cwd and _is_under_workspaces_root(initial_cwd):
        Path(initial_cwd).mkdir(parents=True, exist_ok=True)


def delete_session_scratchpad(session_id: str) -> None:
    """Remove the session's scratchpad folder. Failures are logged, not raised:
    the session itself is already gone by the time this runs."""
    if not is_valid_session_id(session_id):
        return
    path = Path(get_session_scratchpad_dir(session_id))
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.warning("Could not delete scratchpad %s: %s", path, exc)
