from __future__ import annotations

from dataclasses import dataclass, replace
import threading

from src.utils.approval_modes import APPROVAL_MODE_DEFAULT
from src.utils.heartbeat_settings import DEFAULT_HEARTBEAT_SETTINGS
from src.utils.session_model import Session


@dataclass(frozen=True)
class RuntimeSettings:
    profile_name: str | None
    profile_revision: int
    approval_mode: str
    approval_mode_revision: int
    heartbeat_settings: dict
    heartbeat_settings_revision: int


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


def initialize(session_id: str, session: Session) -> RuntimeSettings:
    with _lock:
        current = _settings.get(session_id)
        if current is None:
            current = RuntimeSettings(
                profile_name=session.profile_name,
                profile_revision=0,
                approval_mode=session.approval_mode or APPROVAL_MODE_DEFAULT,
                approval_mode_revision=0,
                heartbeat_settings=dict(
                    session.session_data.get("heartbeat_settings")
                    or DEFAULT_HEARTBEAT_SETTINGS
                ),
                heartbeat_settings_revision=0,
            )
            _settings[session_id] = current
        return current


def snapshot(session_id: str, session: Session) -> RuntimeSettings:
    return initialize(session_id, session)


def set_profile(
    session_id: str, session: Session, profile_name: str | None
) -> RuntimeSettings:
    with _lock:
        current = initialize(session_id, session)
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
        current = initialize(session_id, session)
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
        current = initialize(session_id, session)
        if current.heartbeat_settings == heartbeat_settings:
            return current
        updated = replace(
            current,
            heartbeat_settings=dict(heartbeat_settings),
            heartbeat_settings_revision=current.heartbeat_settings_revision + 1,
        )
        _settings[session_id] = updated
        return updated


def merge_into_session(session_id: str, session: Session) -> RuntimeSettings:
    current = snapshot(session_id, session)
    session.profile_name = current.profile_name
    session.approval_mode = current.approval_mode
    session.session_data["heartbeat_settings"] = current.heartbeat_settings
    return current


def payload(settings: RuntimeSettings) -> dict:
    return {
        "profileName": settings.profile_name,
        "profileRevision": settings.profile_revision,
        "approvalMode": settings.approval_mode,
        "approvalModeRevision": settings.approval_mode_revision,
        "heartbeatSettings": settings.heartbeat_settings,
        "heartbeatSettingsRevision": settings.heartbeat_settings_revision,
    }


def discard(session_id: str) -> None:
    with _lock:
        _settings.pop(session_id, None)
        _persistence_locks.pop(session_id, None)
