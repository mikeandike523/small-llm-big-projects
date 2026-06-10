from __future__ import annotations
import os


def _effective_cwd(session_cwd: str | None) -> str:
    """Return session_cwd if set, else fall back to the process CWD."""
    return session_cwd or os.getcwd()


def _resolve_path(path: str, session_cwd: str | None) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(_effective_cwd(session_cwd), path))
