"""Persisting a settings change without loading the session.

Profile, approval mode and heartbeat settings are session-level events
(`profile_set`, `approval_mode_set`, `heartbeat_settings_set`). A change
appends its one event (plus the session_meta copies of that setting) in one
transaction, instead of rebuilding the session and diffing it on save.

The persist cursor (see _session_event_emit.py) remembers the last saved value
of each setting. It is updated here too, under the same persistence lock as
every save, so the agent's next save (whose Session copy picks the new value up
from runtime_settings) sees nothing new and does not append the event again.
With no cursor (cold), there is nothing to update: the next load rebuilds it
from MySQL, which already holds the event.
"""

from __future__ import annotations

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components import runtime_settings
from src.ui_connector.socket_handler_components._session_event_emit import (
    load_cursor,
    save_cursor,
)
from src.utils.session_events import (
    EVT_APPROVAL_MODE_SET,
    EVT_HEARTBEAT_SETTINGS_SET,
    EVT_PROFILE_SET,
    approval_mode_payload,
    heartbeat_settings_payload,
    profile_payload,
)
from src.utils.sql.chat_history_cache_db import append_setting_event


def _persist(
    session_id: str,
    event_type: str,
    payload: dict,
    meta_updates: dict,
    cursor_field: str,
    cursor_value,
) -> None:
    with runtime_settings.persistence_lock(session_id):
        append_setting_event(session_id, event_type, payload, meta_updates)
        r = _state._get_redis()
        cursor = load_cursor(r, session_id)
        if cursor:
            cursor[cursor_field] = cursor_value
            save_cursor(r, session_id, cursor, _state._SESSION_TTL)


def persist_profile(session_id: str, profile_name: str | None) -> None:
    """Save a profile change. The context-usage snapshot belonged to the old
    profile, so its durable copy is cleared too (see clear_context_usage)."""
    _persist(
        session_id,
        EVT_PROFILE_SET,
        profile_payload(profile_name),
        {"profile_name": profile_name, "last_context_usage": None},
        "profile_name",
        profile_name,
    )


def persist_approval_mode(session_id: str, approval_mode: str) -> None:
    _persist(
        session_id,
        EVT_APPROVAL_MODE_SET,
        approval_mode_payload(approval_mode),
        {},
        "approval_mode",
        approval_mode,
    )


def persist_heartbeat_settings(session_id: str, heartbeat_settings: dict) -> None:
    _persist(
        session_id,
        EVT_HEARTBEAT_SETTINGS_SET,
        heartbeat_settings_payload(heartbeat_settings),
        {"heartbeat_enabled": 1 if heartbeat_settings.get("enabled") else 0},
        "heartbeat_settings",
        dict(heartbeat_settings),
    )
