"""Persisting a settings change without loading the session.

Profile, approval mode, heartbeat and email settings are session-level events
(`profile_set`, `approval_mode_set`, `heartbeat_settings_set`,
`email_settings_set`). A change
appends its one event (plus the session_meta copies of that setting) in one
transaction, under the same persistence lock as every session write. A running
turn's Session copy picks the new value up from runtime_settings on its next
write (session_writes.py), which writes only its own events.
"""

from __future__ import annotations

from src.ui_connector.socket_handler_components import runtime_settings
from src.utils.session_events import (
    EVT_APPROVAL_MODE_SET,
    EVT_EMAIL_SETTINGS_SET,
    EVT_HEARTBEAT_SETTINGS_SET,
    EVT_PROFILE_SET,
    approval_mode_payload,
    email_settings_payload,
    heartbeat_settings_payload,
    profile_payload,
)
from src.utils.sql.chat_history_cache_db import append_setting_event


def _persist(
    session_id: str, event_type: str, payload: dict, meta_updates: dict
) -> None:
    with runtime_settings.persistence_lock(session_id):
        append_setting_event(session_id, event_type, payload, meta_updates)


def persist_profile(session_id: str, profile_name: str | None) -> None:
    """Save a profile change. The context-usage snapshot belonged to the old
    profile, so its durable copy is cleared too (see clear_context_usage)."""
    _persist(
        session_id,
        EVT_PROFILE_SET,
        profile_payload(profile_name),
        {"profile_name": profile_name, "last_context_usage": None},
    )


def persist_approval_mode(session_id: str, approval_mode: str) -> None:
    _persist(
        session_id,
        EVT_APPROVAL_MODE_SET,
        approval_mode_payload(approval_mode),
        {},
    )


def persist_heartbeat_settings(session_id: str, heartbeat_settings: dict) -> None:
    _persist(
        session_id,
        EVT_HEARTBEAT_SETTINGS_SET,
        heartbeat_settings_payload(heartbeat_settings),
        {"heartbeat_enabled": 1 if heartbeat_settings.get("enabled") else 0},
    )


def persist_email_settings(session_id: str, email_settings: dict) -> None:
    """Save email settings plus their session_meta copies in one transaction.

    `session_meta.email_alias` is UNIQUE, so a concurrent claim of the same
    alias by another session fails here with a duplicate-key IntegrityError
    and nothing is written (the caller maps it to HTTP 409). Only this path
    writes the email columns; ordinary session saves never touch them.
    """
    alias = email_settings.get("alias") or None
    _persist(
        session_id,
        EVT_EMAIL_SETTINGS_SET,
        email_settings_payload(email_settings),
        {
            "email_enabled": 1 if email_settings.get("enabled") else 0,
            "email_alias": alias,
            "email_alias_claimed_at": (
                email_settings.get("alias_claimed_at") if alias else None
            ),
        },
    )
