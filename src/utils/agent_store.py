"""Agents: the identity and settings a pool of sessions shares.

Reads are cached in this process, because session settings are read on every
tool call and LLM dispatch, and every write goes through here (one server
process at a time). A changed setting therefore reaches running sessions at the
same moment it would for a normal session: their next read.
"""

from __future__ import annotations

import threading
import time
import uuid

from src.utils.agent_dirs import ensure_agent_dirs
from src.utils.agent_settings import AgentIdentity, AgentSettings
from src.utils.slugs import slug_candidates, slugify
from src.utils.sql import agents_db
from src.utils.sql.agents_db import Agent

_SLUG_KEY = "uq_agents_slug"
_lock = threading.Lock()
_cache: dict[str, Agent] = {}


class AgentConflictError(ValueError):
    """Another agent holds this name or email; ``field`` says which."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


def invalidate(agent_id: str) -> None:
    with _lock:
        _cache.pop(agent_id, None)


def get_agent(agent_id: str) -> Agent | None:
    with _lock:
        cached = _cache.get(agent_id)
    if cached is not None:
        return cached
    agent = agents_db.load_agent(agent_id)
    if agent is not None:
        with _lock:
            _cache[agent_id] = agent
    return agent


def agent_for_session(session_id: str) -> Agent | None:
    agent_id = agents_db.agent_id_for_session(session_id)
    return get_agent(agent_id) if agent_id is not None else None


def _check_conflict(identity: AgentIdentity, exclude_agent_id: str | None) -> None:
    field = agents_db.identity_conflict(
        identity.name_key, identity.email, exclude_agent_id=exclude_agent_id
    )
    if field == "name":
        raise AgentConflictError(
            f"The name {identity.name!r} is already used by another agent.",
            field="name",
        )
    if field == "email":
        raise AgentConflictError(
            f"{identity.email} is already used by another agent.", field="email"
        )


def _conflict_from_duplicate(exc: Exception, identity: AgentIdentity):
    """Two simultaneous claims: the unique keys decide, with the same message."""
    field = "email" if agents_db.duplicate_key_names(exc, "uq_agents_email") else "name"
    value = identity.email if field == "email" else identity.name
    return AgentConflictError(f"{value} is already used by another agent.", field=field)


def create_agent(identity: AgentIdentity, settings: AgentSettings) -> Agent:
    _check_conflict(identity, None)
    base_slug = slugify(identity.name, fallback="agent")
    for slug in slug_candidates(base_slug):
        agent = Agent(
            id=str(uuid.uuid4()),
            slug=slug,
            name=identity.name,
            email=identity.email,
            registered_at=time.time(),
            enabled=settings.enabled,
            allowed_senders=tuple(settings.allowed_senders),
            profile_name=settings.profile_name,
            approval_mode=settings.approval_mode,
            automation_approval_policy=settings.automation_approval_policy,
            created_at=time.time(),
        )
        try:
            agents_db.insert_agent(agent, name_key=identity.name_key)
        except Exception as exc:
            if not agents_db.is_duplicate_key_error(exc):
                raise
            if agents_db.duplicate_key_names(exc, _SLUG_KEY):
                continue
            raise _conflict_from_duplicate(exc, identity) from exc
        ensure_agent_dirs(slug)
        return agent
    raise AssertionError("slug_candidates never ends")


def update_settings(agent_id: str, settings: AgentSettings) -> None:
    agents_db.update_agent_settings(
        agent_id,
        enabled=settings.enabled,
        allowed_senders=settings.allowed_senders,
        profile_name=settings.profile_name,
        approval_mode=settings.approval_mode,
        automation_approval_policy=settings.automation_approval_policy,
    )
    invalidate(agent_id)


def register(agent_id: str, identity: AgentIdentity) -> None:
    """Claim a name + email pair. Only mail received from now on is answered."""
    _check_conflict(identity, agent_id)
    try:
        agents_db.set_agent_identity(
            agent_id,
            name=identity.name,
            name_key=identity.name_key,
            email=identity.email,
            registered_at=time.time(),
        )
    except Exception as exc:
        if agents_db.is_duplicate_key_error(exc):
            raise _conflict_from_duplicate(exc, identity) from exc
        raise
    invalidate(agent_id)


def unregister(agent_id: str) -> None:
    """Release the name + email pair; the agent and its folder remain."""
    agents_db.set_agent_identity(
        agent_id, name=None, name_key=None, email=None, registered_at=None
    )
    invalidate(agent_id)


def delete(agent_id: str) -> None:
    agents_db.delete_agent(agent_id)
    invalidate(agent_id)
