"""Finding or creating the session that answers one conversation.

A conversation is (agent, Gmail thread, sender): a person joining someone else's
thread is a new conversation. Only the runner's single thread calls these, so
two emails cannot spawn two sessions for one conversation.
"""

from __future__ import annotations

import logging
import uuid

from src.channels.email.inbound_store import InboundEmail
from src.utils.agent_dirs import ensure_user_dir
from src.utils.agent_store import get_agent
from src.utils.session_dirs import ensure_session_dirs
from src.utils.session_events import derive_meta, session_created_payload
from src.utils.session_model import Session
from src.utils.slugs import sender_slug_base, slug_candidates
from src.utils.sql import agents_db
from src.utils.sql.agents_db import Agent, AgentSender
from src.utils.sql.chat_history_cache_db import persist_save

logger = logging.getLogger(__name__)


def _ensure_sender(agent: Agent, row: InboundEmail) -> AgentSender:
    """This person's record. The slug is chosen once, from the first name seen
    (the address is what identifies them), and later names only update the
    dashboard."""
    existing = agents_db.load_sender(agent.id, row.sender_address)
    if existing is not None:
        name = row.sender_display_name
        if name and name != existing.display_name:
            agents_db.update_sender_display_name(agent.id, row.sender_address, name)
        return existing
    taken = agents_db.list_sender_slugs(agent.id)
    base = sender_slug_base(row.sender_display_name, row.sender_address)
    slug = next(c for c in slug_candidates(base) if c not in taken)
    sender = AgentSender(
        agent_id=agent.id,
        sender_address=row.sender_address,
        slug=slug,
        display_name=row.sender_display_name,
    )
    agents_db.insert_sender(sender)
    return sender


def _create_session(agent: Agent, user_dir: str) -> str:
    session_id = str(uuid.uuid4())
    ensure_session_dirs(session_id, None)
    session = Session(
        session_id=session_id,
        initial_cwd=user_dir,
        profile_name=agent.profile_name,
        approval_mode=agent.approval_mode,
        # The starting folder holds what people send, so nothing in it may load
        # as a skill or tool.
        load_custom_skills_tools=False,
        startup_done=True,
        agent_id=agent.id,
    )
    meta = derive_meta(session)
    persist_save(
        session_id,
        [("session_created", session_created_payload(session))],
        [],
        [],
        dict(
            created_at=session.created_at,
            schema_version=session.schema_version,
            profile_name=session.profile_name,
            initial_cwd=session.initial_cwd,
            current_cwd=None,
            total_cost_usd=0.0,
            turn_count=meta["turn_count"],
            recent_task_titles=meta["recent_task_titles"],
            task_title_count=meta["task_title_count"],
            interim_response_as_thinking=session.interim_response_as_thinking,
            load_custom_skills_tools=session.load_custom_skills_tools,
            agent_id=agent.id,
        ),
    )
    return session_id


def session_for_email(row: InboundEmail) -> str:
    """The conversation's session id, spawning the session on its first email."""
    agent = get_agent(row.agent_id)
    if agent is None:
        raise LookupError(f"Agent {row.agent_id} does not exist.")
    sender = _ensure_sender(agent, row)
    existing = agents_db.conversation_session(
        agent.id, row.gmail_thread_id, row.sender_address
    )
    if existing is not None:
        return existing
    session_id = _create_session(agent, ensure_user_dir(agent.slug, sender.slug))
    agents_db.insert_conversation(
        agent.id, row.gmail_thread_id, row.sender_address, session_id
    )
    logger.info(
        "Spawned session: agent_id=%s session_id=%s sender=%s thread=%s",
        agent.id,
        session_id,
        row.sender_address,
        row.gmail_thread_id,
    )
    return session_id


def ensure_user_folder(row: InboundEmail) -> None:
    """Re-create the person's folder if it is gone (it is the session's cwd, and
    nothing else re-creates it). The email header does not name it: the session
    already starts there."""
    agent = get_agent(row.agent_id)
    if agent is None:
        raise LookupError(f"Agent {row.agent_id} does not exist.")
    sender = _ensure_sender(agent, row)
    ensure_user_dir(agent.slug, sender.slug)
