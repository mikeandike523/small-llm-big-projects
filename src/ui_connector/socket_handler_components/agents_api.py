"""HTTP routes for agents and the dashboard's session pools.

A name + email pair is committed when the agent is created and never edited.
Retiring releases it (the agent keeps it for display); unretiring claims it
again and reactivates the same pool. Each must be unique among active agents,
ignoring case; the unique keys on ``agents`` close the race between two
simultaneous claims.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import app
from src.ui_connector.socket_handler_components.session_store import _delete_sessions
from src.data import get_pool
from src.utils import agent_store
from src.utils.agent_dirs import get_agent_workspace
from src.utils.agent_settings import (
    InvalidAgentSettingsError,
    parse_agent_identity,
    parse_agent_settings,
)
from src.utils.agent_store import AgentConflictError, AgentUnretireError
from src.utils.sql import agents_db
from src.utils.sql.agents_db import Agent

logger = logging.getLogger(__name__)


def _invalid(exc: InvalidAgentSettingsError):
    return jsonify({"error": str(exc), "field": exc.field}), 400


def _conflict(exc: AgentConflictError):
    return jsonify({"error": str(exc), "field": exc.field}), 409


def _not_found():
    return jsonify({"error": "Agent not found"}), 404


def _check_profile_exists(profile_name: str) -> None:
    with get_pool().get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (profile_name,))
        if cur.fetchone() is None:
            raise InvalidAgentSettingsError(
                f"Profile '{profile_name}' does not exist.", field="profile_name"
            )


def pool_session_status(session_id: str, latest_email_status: str | None) -> str:
    """One word for the dashboard. Live turn state wins; otherwise the outcome of
    the latest email says how the conversation stands."""
    with _state._pending_approvals_lock:
        if session_id in _state._pending_approvals:
            return "waiting_approval"
    if _state.is_turn_reserved(session_id):
        return "running"
    if latest_email_status in ("queued", "failed", "cancelled", "interrupted"):
        return latest_email_status
    return "idle"


def _last_activity_at(rows: list[dict]) -> float | None:
    """The newest email in the pool: the same order the pool's rows use."""
    times = [float(row["received_at"]) for row in rows if row.get("received_at")]
    return max(times) if times else None


def _agent_json(agent: Agent, pool_rows: list[dict]) -> dict:
    rows = [row for row in pool_rows if row["agent_id"] == agent.id]
    return {
        "id": agent.id,
        "slug": agent.slug,
        "name": agent.name,
        "email": agent.email,
        "enabled": agent.enabled,
        "allowed_senders": list(agent.allowed_senders),
        "profile_name": agent.profile_name,
        "approval_mode": agent.approval_mode,
        "automation_approval_policy": agent.automation_approval_policy,
        "workspace": get_agent_workspace(agent.slug),
        "created_at": agent.created_at,
        "retired_at": agent.retired_at,
        "last_activity_at": _last_activity_at(rows),
        "sessions": [
            {
                "session_id": row["session_id"],
                "sender_address": row["sender_address"],
                "display_name": row.get("display_name"),
                "gmail_thread_id": row["gmail_thread_id"],
                "subject": row.get("subject") or "",
                "status": pool_session_status(row["session_id"], row.get("status")),
            }
            for row in rows
        ],
    }


def _notify_runner() -> None:
    from src.channels.email.email_runner import notify_email_runner

    notify_email_runner()


def _discard_queued(agent_id: str) -> None:
    from src.channels.email.inbound_store import discard_queued_for_agent

    discarded = discard_queued_for_agent(agent_id)
    if discarded:
        logger.info("Discarded %d queued email(s): agent_id=%s", discarded, agent_id)


def _has_running_turn(agent_id: str) -> bool:
    return any(
        _state.is_turn_reserved(session_id)
        for session_id in agents_db.agent_session_ids(agent_id)
    )


@app.route("/api/agents", methods=["GET"])
def api_list_agents():
    pool_rows = agents_db.list_pool_rows()
    return jsonify([_agent_json(a, pool_rows) for a in agents_db.list_agents()])


@app.route("/api/agents", methods=["POST"])
def api_create_agent():
    data = request.get_json(force=True, silent=True) or {}
    try:
        identity = parse_agent_identity(data)
        settings = parse_agent_settings(data)
        _check_profile_exists(settings.profile_name)
        agent = agent_store.create_agent(identity, settings)
    except InvalidAgentSettingsError as exc:
        return _invalid(exc)
    except AgentConflictError as exc:
        return _conflict(exc)
    logger.info("Agent created: id=%s slug=%s", agent.id, agent.slug)
    return jsonify(_agent_json(agent, [])), 201


@app.route("/api/agents/<agent_id>", methods=["PATCH"])
def api_update_agent(agent_id: str):
    if agent_store.get_agent(agent_id) is None:
        return _not_found()
    data = request.get_json(force=True, silent=True) or {}
    try:
        settings = parse_agent_settings(data)
        _check_profile_exists(settings.profile_name)
    except InvalidAgentSettingsError as exc:
        return _invalid(exc)
    agent_store.update_settings(agent_id, settings)
    if not settings.enabled:
        _discard_queued(agent_id)
    _notify_runner()
    return jsonify({"ok": True})


@app.route("/api/agents/<agent_id>/retire", methods=["POST"])
def api_retire_agent(agent_id: str):
    agent = agent_store.get_agent(agent_id)
    if agent is None:
        return _not_found()
    if agent.is_retired:
        return jsonify({"ok": True})
    if _has_running_turn(agent_id):
        return (
            jsonify({"error": "Stop this agent's running turns first."}),
            409,
        )
    _discard_queued(agent_id)
    agent_store.retire(agent_id)
    logger.info("Agent retired: id=%s slug=%s", agent.id, agent.slug)
    _notify_runner()
    return jsonify({"ok": True})


@app.route("/api/agents/<agent_id>/unretire", methods=["POST"])
def api_unretire_agent(agent_id: str):
    if agent_store.get_agent(agent_id) is None:
        return _not_found()
    try:
        agent_store.unretire(agent_id)
    except AgentConflictError as exc:
        return _conflict(exc)
    except AgentUnretireError as exc:
        return jsonify({"error": str(exc)}), 409
    logger.info("Agent unretired: id=%s", agent_id)
    _notify_runner()
    return jsonify({"ok": True})


@app.route("/api/agents/<agent_id>", methods=["DELETE"])
def api_delete_agent(agent_id: str):
    """Delete the record and its sessions. The agent's folder stays on disk.

    An active agent is retired first, under the same rules as retiring it."""
    agent = agent_store.get_agent(agent_id)
    if agent is None:
        return _not_found()
    if _has_running_turn(agent_id):
        return jsonify({"error": "Stop this agent's running turns first."}), 409
    if not agent.is_retired:
        _discard_queued(agent_id)
        agent_store.retire(agent_id)
        _notify_runner()
    _delete_sessions(agents_db.agent_session_ids(agent_id))
    agent_store.delete(agent_id)
    logger.info("Agent deleted: id=%s slug=%s", agent.id, agent.slug)
    return jsonify({"ok": True})
