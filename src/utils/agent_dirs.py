"""An agent's folders under ``~/.slbp/agents``.

    ~/.slbp/agents/<agent-slug>/workspace/
      SOUL.md              loaded into the system prompt every subturn
      MEMORY.md            long-term memory; the prompt only says where it is
      users/<user-slug>/   a person's files; the session's starting folder

These folders are kept when sessions or the agent are deleted: they are the
agent's identity. Re-creating an agent with the same name reuses them.
"""

from __future__ import annotations

from pathlib import Path

SOUL_FILE = "SOUL.md"
MEMORY_FILE = "MEMORY.md"
USERS_DIR = "users"


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


def get_agent_workspace(agent_slug: str) -> str:
    return _portable(Path.home() / ".slbp" / "agents" / agent_slug / "workspace")


def get_user_dir(agent_slug: str, user_slug: str) -> str:
    return _portable(Path(get_agent_workspace(agent_slug)) / USERS_DIR / user_slug)


def ensure_agent_dirs(agent_slug: str) -> None:
    """Create the workspace and its empty identity files. Raises OSError."""
    workspace = Path(get_agent_workspace(agent_slug))
    (workspace / USERS_DIR).mkdir(parents=True, exist_ok=True)
    for name in (SOUL_FILE, MEMORY_FILE):
        (workspace / name).touch(exist_ok=True)


def ensure_user_dir(agent_slug: str, user_slug: str) -> str:
    """Create a person's folder (and the workspace) and return its path."""
    ensure_agent_dirs(agent_slug)
    path = Path(get_user_dir(agent_slug, user_slug))
    path.mkdir(parents=True, exist_ok=True)
    return _portable(path)
