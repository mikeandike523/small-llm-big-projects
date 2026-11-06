from __future__ import annotations

from dataclasses import dataclass, replace
import threading

from src.utils.agent_store import get_agent
from src.utils.approval_modes import APPROVAL_MODE_DEFAULT
from src.utils.email_settings import normalize_email_settings
from src.utils.heartbeat_settings import normalize_heartbeat_settings
from src.utils.session_model import Session


@dataclass(frozen=True)
class RuntimeSettings:
    profile_name: str | None
    profile_revision: int
    approval_mode: str
    approval_mode_revision: int
    heartbeat_settings: dict
    heartbeat_settings_revision: int
    email_settings: dict
    email_settings_revision: int
    # Set for a session in an agent's pool: the agent's profile and approval
    # mode replace the session's own on every read (see _with_agent_settings).
    agent_id: str | None = None


_lock = threading.RLock()
_settings: dict[str, RuntimeSettings] = {}
_persistence_locks: dict[str, threading.RLock] = {}


def persistence_lock(session_id: str) -> threading.RLock:
    with _lock:
        lock = _persistence_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _persistence_locks[session_id] = lock
        return lock


def _with_agent_settings(current: RuntimeSettings) -> RuntimeSettings:
    """Read live from the agent, so a change reaches running sessions at their
    next read: the same timing as changing a normal session's own settings."""
    if current.agent_id is None:
        return current
    agent = get_agent(current.agent_id)
    if agent is None:
        return current
    return replace(
        current,
        profile_name=agent.profile_name,
        approval_mode=agent.approval_mode,
    )


def _initialize_stored(session_id: str, session: Session) -> RuntimeSettings:
    with _lock:
        current = _settings.get(session_id)
        if current is None:
            current = RuntimeSettings(
                profile_name=session.profile_name,
                profile_revision=0,
                approval_mode=session.approval_mode or APPROVAL_MODE_DEFAULT,
                approval_mode_revision=0,
                heartbeat_settings=normalize_heartbeat_settings(
                    session.session_data.get("heartbeat_settings")
                ),
                heartbeat_settings_revision=0,
                email_settings=normalize_email_settings(
                    session.session_data.get("email_settings")
                ),
                email_settings_revision=0,
                agent_id=session.agent_id,
            )
            _settings[session_id] = current
        return current


def initialize(session_id: str, session: Session) -> RuntimeSettings:
    return _with_agent_settings(_initialize_stored(session_id, session))


def peek(session_id: str) -> RuntimeSettings | None:
    """Return the live settings if this process has initialized them, else None."""
    with _lock:
        current = _settings.get(session_id)
    return _with_agent_settings(current) if current is not None else None


def snapshot(session_id: str, session: Session) -> RuntimeSettings:
    return initialize(session_id, session)


def set_profile(
    session_id: str, session: Session, profile_name: str | None
) -> RuntimeSettings:
    with _lock:
        current = _initialize_stored(session_id, session)
        if current.profile_name == profile_name:
            return current
        updated = replace(
            current,
            profile_name=profile_name,
            profile_revision=current.profile_revision + 1,
        )
        _settings[session_id] = updated
        return updated


def set_approval_mode(
    session_id: str, session: Session, approval_mode: str
) -> RuntimeSettings:
    with _lock:
        current = _initialize_stored(session_id, session)
        if current.approval_mode == approval_mode:
            return current
        updated = replace(
            current,
            approval_mode=approval_mode,
            approval_mode_revision=current.approval_mode_revision + 1,
        )
        _settings[session_id] = updated
        return updated


def set_heartbeat_settings(
    session_id: str, session: Session, heartbeat_settings: dict
) -> RuntimeSettings:
    with _lock:
        current = _initialize_stored(session_id, session)
        if current.heartbeat_settings == heartbeat_settings:
            return current
        updated = replace(
            current,
            heartbeat_settings=dict(heartbeat_settings),
            heartbeat_settings_revision=current.heartbeat_settings_revision + 1,
        )
        _settings[session_id] = updated
        return updated


def set_email_settings(
    session_id: str, session: Session, email_settings: dict
) -> RuntimeSettings:
    with _lock:
        current = _initialize_stored(session_id, session)
        if current.email_settings == email_settings:
            return current
        updated = replace(
            current,
            email_settings=dict(email_settings),
            email_settings_revision=current.email_settings_revision + 1,
        )
        _settings[session_id] = updated
        return updated


def merge_into_session(session_id: str, session: Session) -> RuntimeSettings:
    current = snapshot(session_id, session)
    session.profile_name = current.profile_name
    session.approval_mode = current.approval_mode
    session.session_data["heartbeat_settings"] = current.heartbeat_settings
    session.session_data["email_settings"] = current.email_settings
    return current


def payload(settings: RuntimeSettings) -> dict:
    return {
        "profileName": settings.profile_name,
        "profileRevision": settings.profile_revision,
        "approvalMode": settings.approval_mode,
        "approvalModeRevision": settings.approval_mode_revision,
        "heartbeatSettings": settings.heartbeat_settings,
        "heartbeatSettingsRevision": settings.heartbeat_settings_revision,
        "emailSettings": settings.email_settings,
        "emailSettingsRevision": settings.email_settings_revision,
    }


def discard(session_id: str) -> None:
    with _lock:
        _settings.pop(session_id, None)
        _persistence_locks.pop(session_id, None)
