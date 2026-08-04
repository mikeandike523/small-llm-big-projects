"""Slack session management helpers.

Handles the lifecycle of sessions initiated through Slack DMs:
  - Looking up an existing slack_session_mapping for a (team, user) pair.
  - Verifying the mapped session_id still exists in the session_meta table.
  - Creating a fresh backend session and persisting a new mapping row.

This module deliberately stays independent of the Slack SDK types so it
can be tested without a running Socket Mode connection.
"""

from __future__ import annotations

import logging
import uuid as _uuid_module

from src.utils.sql.session_store_db import (
    append_events,
    load_session_meta,
    upsert_session_meta,
)
from src.utils.session_model import Session
from src.utils.session_events import session_created_payload, derive_meta
from src.utils.env_info import get_default_workspace_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_slack_team_id(request_payload: dict) -> str | None:
    """Extract the team/workspace ID from a Slack Socket Mode request payload.

    Checks the top-level ``team_id`` field first, then falls back to the
    first entry in the ``authorizations`` array.
    """
    team_id = request_payload.get("team_id")
    if team_id:
        return str(team_id)
    authorizations = request_payload.get("authorizations")
    if authorizations and isinstance(authorizations, list) and len(authorizations) > 0:
        return str(authorizations[0].get("team_id") or "")
    return None


def resolve_slack_session(team_id: str, user_id: str) -> str:
    """Look up or create a session for a Slack DM user.

    Returns the session_id and logs the outcome.

    1.  Query ``slack_session_mappings`` for an existing mapping.
    2a. Found → verify the session still exists in ``session_meta``.
        - Exists: log ``found`` and return the session_id.
        - Missing: log a warning that the mapping is stale, then fall
          through to creation.
    2b. Not found → create a fresh session and store the mapping.
    3.  Return the (new) session_id.
    """
    existing = _lookup_slack_session(team_id, user_id)

    if existing is not None:
        if _session_exists_in_db(existing):
            logger.info(
                "Slack: found active session %s for user %s (team %s)",
                existing, user_id, team_id,
            )
            return existing
        else:
            logger.warning(
                "Slack: session %s found in mapping but missing from DB "
                "for user %s (team %s) — creating a new one",
                existing, user_id, team_id,
            )

    new_session_id = _create_slack_session()
    _store_slack_session_mapping(team_id, user_id, new_session_id)
    logger.info(
        "Slack: mapped user %s (team %s) to new session %s",
        user_id, team_id, new_session_id,
    )
    return new_session_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lookup_slack_session(team_id: str, user_id: str) -> str | None:
    """Return the session_id associated with a Slack user, or None."""
    from src.data import get_pool

    try:
        pool = get_pool()
    except Exception as exc:
        logger.error("Slack session lookup: unable to get DB pool: %s", exc)
        return None

    sql = """
        SELECT session_id
        FROM slack_session_mappings
        WHERE slack_team_id = %s AND slack_user_id = %s
    """
    try:
        with pool.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (team_id, user_id))
                row = cur.fetchone()
    except Exception as exc:
        logger.error("Slack session lookup: query failed: %s", exc)
        return None

    if row:
        return str(row[0])
    return None


def _session_exists_in_db(session_id: str) -> bool:
    """Return True if the session_id exists in the session_meta table."""
    try:
        meta = load_session_meta(session_id)
    except Exception as exc:
        logger.error("Slack: error checking session %s in DB: %s", session_id, exc)
        return False
    return meta is not None


def _store_slack_session_mapping(team_id: str, user_id: str, session_id: str) -> None:
    """Insert or update the slack_session_mappings row for this user."""
    from src.data import get_pool

    try:
        pool = get_pool()
    except Exception as exc:
        logger.error("Slack: unable to get DB pool to store mapping: %s", exc)
        return

    sql = """
        INSERT INTO slack_session_mappings (slack_team_id, slack_user_id, session_id)
        VALUES (%s, %s, %s)
        AS incoming
        ON DUPLICATE KEY UPDATE
            session_id = incoming.session_id,
            updated_at = CURRENT_TIMESTAMP(3)
    """
    try:
        with pool.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (team_id, user_id, session_id))
            conn.commit()
    except Exception as exc:
        logger.error("Slack: failed to store session mapping: %s", exc)


def _create_slack_session() -> str:
    """Create a new backend session for a Slack user and return its session_id.

    Persists the ``session_created`` event and metadata row directly into
    MySQL (bypassing the Flask HTTP API) so the session is immediately
    available for the next step of processing.
    """
    session_id = str(_uuid_module.uuid4())
    workspace_dir = get_default_workspace_dir()

    session = Session(
        session_id=session_id,
        initial_cwd=workspace_dir,
        profile_name=None,
    )

    try:
        append_events(
            session_id,
            [("session_created", session_created_payload(session))],
        )
        meta = derive_meta(session)
        upsert_session_meta(
            session_id,
            created_at=session.created_at,
            schema_version=session.schema_version,
            profile_name=session.profile_name,
            initial_cwd=session.initial_cwd or "",
            current_cwd=None,
            total_cost_usd=0.0,
            turn_count=meta["turn_count"],
            task_titles=meta["task_titles"],
            interim_response_as_thinking=session.interim_response_as_thinking,
            skills_path=session.skills_path,
            custom_tools_path=session.custom_tools_path,
            memory={},
        )
    except Exception as exc:
        logger.error(
            "Slack: failed to persist new session %s: %s", session_id, exc,
        )
        raise

    logger.info(
        "Slack: created new session %s (cwd=%s)",
        session_id, workspace_dir,
    )
    return session_id