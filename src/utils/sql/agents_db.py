"""MySQL access for agents, the people they talk to and their conversations."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass

from src.data import get_pool

MYSQL_DUPLICATE_KEY_ERRNO = 1062

_AGENT_COLS = (
    "id, slug, name, email, registered_at, enabled, allowed_senders, profile_name, "
    "approval_mode, automation_approval_policy, created_at"
)


@dataclass(frozen=True)
class Agent:
    id: str
    slug: str
    name: str | None
    email: str | None
    registered_at: float | None
    enabled: bool
    allowed_senders: tuple[str, ...]
    profile_name: str
    approval_mode: str
    automation_approval_policy: str
    created_at: float


@dataclass(frozen=True)
class AgentSender:
    agent_id: str
    sender_address: str
    slug: str
    display_name: str | None


def is_duplicate_key_error(exc: BaseException) -> bool:
    return getattr(exc, "errno", None) == MYSQL_DUPLICATE_KEY_ERRNO


def duplicate_key_names(exc: BaseException, key: str) -> bool:
    """True when a duplicate-key error is about the unique key ``key``."""
    return key in str(getattr(exc, "msg", "") or exc)


def _row_to_agent(row: dict) -> Agent:
    senders = row.get("allowed_senders")
    if isinstance(senders, (str, bytes, bytearray)):
        senders = json.loads(senders)
    registered_at = row.get("registered_at")
    return Agent(
        id=str(row["id"]),
        slug=str(row["slug"]),
        name=row.get("name"),
        email=row.get("email"),
        registered_at=float(registered_at) if registered_at is not None else None,
        enabled=bool(row.get("enabled")),
        allowed_senders=tuple(senders or ()),
        profile_name=str(row["profile_name"]),
        approval_mode=str(row["approval_mode"]),
        automation_approval_policy=str(row["automation_approval_policy"]),
        created_at=float(row.get("created_at") or 0.0),
    )


def _fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    with get_pool().get_connection() as conn, conn.cursor(dictionary=True) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _execute(sql: str, params: tuple = ()) -> int:
    with get_pool().get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        changed = cur.rowcount
        conn.commit()
    return changed


# -- agents ------------------------------------------------------------------


def list_agents() -> list[Agent]:
    rows = _fetch_all(f"SELECT {_AGENT_COLS} FROM agents ORDER BY created_at ASC")
    return [_row_to_agent(row) for row in rows]


def load_agent(agent_id: str) -> Agent | None:
    rows = _fetch_all(f"SELECT {_AGENT_COLS} FROM agents WHERE id = %s", (agent_id,))
    return _row_to_agent(rows[0]) if rows else None


def load_agents_for_emails(emails: Collection[str]) -> list[Agent]:
    wanted = sorted(set(emails))
    if not wanted:
        return []
    placeholders = ", ".join(["%s"] * len(wanted))
    rows = _fetch_all(
        f"SELECT {_AGENT_COLS} FROM agents WHERE email IN ({placeholders})",
        tuple(wanted),
    )
    return [_row_to_agent(row) for row in rows]


def list_registered_emails() -> set[str]:
    rows = _fetch_all("SELECT email FROM agents WHERE email IS NOT NULL")
    return {str(row["email"]) for row in rows}


def identity_conflict(
    name_key: str, email: str, *, exclude_agent_id: str | None
) -> str | None:
    """Which identity field another agent already holds: name, email or None."""
    rows = _fetch_all(
        "SELECT name_key, email FROM agents "
        "WHERE (name_key = %s OR email = %s) AND id <> %s",
        (name_key, email, exclude_agent_id or ""),
    )
    if any(row.get("name_key") == name_key for row in rows):
        return "name"
    return "email" if rows else None


def insert_agent(agent: Agent, *, name_key: str | None) -> None:
    _execute(
        """
        INSERT INTO agents
            (id, slug, name, name_key, email, registered_at, enabled,
             allowed_senders, profile_name, approval_mode,
             automation_approval_policy, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            agent.id,
            agent.slug,
            agent.name,
            name_key,
            agent.email,
            agent.registered_at,
            1 if agent.enabled else 0,
            json.dumps(list(agent.allowed_senders)),
            agent.profile_name,
            agent.approval_mode,
            agent.automation_approval_policy,
            agent.created_at,
        ),
    )


def update_agent_settings(
    agent_id: str,
    *,
    enabled: bool,
    allowed_senders: list[str],
    profile_name: str,
    approval_mode: str,
    automation_approval_policy: str,
) -> None:
    _execute(
        """
        UPDATE agents SET enabled = %s, allowed_senders = %s, profile_name = %s,
            approval_mode = %s, automation_approval_policy = %s
        WHERE id = %s
        """,
        (
            1 if enabled else 0,
            json.dumps(allowed_senders),
            profile_name,
            approval_mode,
            automation_approval_policy,
            agent_id,
        ),
    )


def set_agent_identity(
    agent_id: str,
    *,
    name: str | None,
    name_key: str | None,
    email: str | None,
    registered_at: float | None,
) -> None:
    _execute(
        "UPDATE agents SET name = %s, name_key = %s, email = %s, registered_at = %s "
        "WHERE id = %s",
        (name, name_key, email, registered_at, agent_id),
    )


def delete_agent(agent_id: str) -> None:
    _execute("DELETE FROM agents WHERE id = %s", (agent_id,))


# -- senders -----------------------------------------------------------------


def load_sender(agent_id: str, sender_address: str) -> AgentSender | None:
    rows = _fetch_all(
        "SELECT agent_id, sender_address, slug, display_name FROM agent_senders "
        "WHERE agent_id = %s AND sender_address = %s",
        (agent_id, sender_address),
    )
    if not rows:
        return None
    row = rows[0]
    return AgentSender(
        agent_id=str(row["agent_id"]),
        sender_address=str(row["sender_address"]),
        slug=str(row["slug"]),
        display_name=row.get("display_name"),
    )


def list_sender_slugs(agent_id: str) -> set[str]:
    rows = _fetch_all("SELECT slug FROM agent_senders WHERE agent_id = %s", (agent_id,))
    return {str(row["slug"]) for row in rows}


def insert_sender(sender: AgentSender) -> None:
    _execute(
        "INSERT INTO agent_senders (agent_id, sender_address, slug, display_name) "
        "VALUES (%s, %s, %s, %s)",
        (sender.agent_id, sender.sender_address, sender.slug, sender.display_name),
    )


def update_sender_display_name(
    agent_id: str, sender_address: str, display_name: str
) -> None:
    _execute(
        "UPDATE agent_senders SET display_name = %s "
        "WHERE agent_id = %s AND sender_address = %s",
        (display_name, agent_id, sender_address),
    )


# -- conversations -----------------------------------------------------------


def conversation_session(
    agent_id: str, gmail_thread_id: str, sender_address: str
) -> str | None:
    rows = _fetch_all(
        "SELECT session_id FROM agent_conversations "
        "WHERE agent_id = %s AND gmail_thread_id = %s AND sender_address = %s",
        (agent_id, gmail_thread_id, sender_address),
    )
    return str(rows[0]["session_id"]) if rows else None


def insert_conversation(
    agent_id: str, gmail_thread_id: str, sender_address: str, session_id: str
) -> None:
    _execute(
        "INSERT INTO agent_conversations "
        "(agent_id, gmail_thread_id, sender_address, session_id) "
        "VALUES (%s, %s, %s, %s)",
        (agent_id, gmail_thread_id, sender_address, session_id),
    )


def conversation_sender(session_id: str) -> str | None:
    rows = _fetch_all(
        "SELECT sender_address FROM agent_conversations WHERE session_id = %s",
        (session_id,),
    )
    return str(rows[0]["sender_address"]) if rows else None


def agent_id_for_session(session_id: str) -> str | None:
    rows = _fetch_all(
        "SELECT agent_id FROM session_meta WHERE session_id = %s", (session_id,)
    )
    if not rows or rows[0].get("agent_id") is None:
        return None
    return str(rows[0]["agent_id"])


def agent_session_ids(agent_id: str) -> list[str]:
    rows = _fetch_all(
        "SELECT session_id FROM session_meta WHERE agent_id = %s", (agent_id,)
    )
    return [str(row["session_id"]) for row in rows]


def list_pool_rows() -> list[dict]:
    """Every conversation with its latest email, newest first (one query, since
    the dashboard polls this)."""
    return _fetch_all("""
        SELECT c.agent_id, c.session_id, c.gmail_thread_id, c.sender_address,
               s.display_name, latest.subject, latest.status, latest.received_at
        FROM agent_conversations c
        LEFT JOIN agent_senders s
          ON s.agent_id = c.agent_id AND s.sender_address = c.sender_address
        LEFT JOIN (
            SELECT session_id, subject, status, received_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY session_id ORDER BY received_at DESC, id DESC
                   ) AS position
            FROM email_inbound
            WHERE session_id IS NOT NULL
        ) latest ON latest.session_id = c.session_id AND latest.position = 1
        ORDER BY latest.received_at DESC
        """)
