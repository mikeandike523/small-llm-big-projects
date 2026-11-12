"""One owner per email address: an agent, or a session holding it as an alias.

Each table's unique key only covers its own side, so a claim takes ``CLAIM_LOCK``
around its check and its write. That is enough because one server process
handles every claim at a time.
"""

from __future__ import annotations

import threading

from src.utils.sql.agents_db import load_agents_for_emails
from src.utils.sql.email_alias_db import find_alias_owner

CLAIM_LOCK = threading.RLock()


def held_by_session_message(email: str) -> str | None:
    """Why an agent cannot claim ``email``, or None when no session holds it."""
    owner = find_alias_owner(email, exclude_session_id="")
    if owner is None:
        return None
    label = f'session "{owner["title"]}"' if owner.get("title") else "a session"
    return f"{email} is already used by {label}. Remove it from that session first."


def held_by_agent_message(email: str) -> str | None:
    """Why a session cannot claim ``email``, or None when no agent holds it."""
    agents = load_agents_for_emails([email])
    if not agents:
        return None
    return f"{email} is already used by agent {agents[0].name}. Retire it first."
