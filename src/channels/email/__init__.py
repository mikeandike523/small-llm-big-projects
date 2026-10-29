"""Email channel startup and lifecycle integration."""

from __future__ import annotations

import logging
import threading

from src.channels.email.credentials import validate_service_account_file
from src.channels.email.watch_daemon import EmailWatchDaemon
from src.channels.email.watch_state import load_gmail_watch_state
from src.utils.param_helper import get_param_value
from src.utils.sql.kv_manager import KVManager

logger = logging.getLogger(__name__)

_daemon_lock = threading.Lock()
_daemon: EmailWatchDaemon | None = None


def _is_email_enabled() -> bool:
    from src.data import get_pool

    pool = get_pool()
    with pool.get_connection() as conn:
        return bool(get_param_value(KVManager(conn), "system.channels.email.enabled"))


def startup_email() -> EmailWatchDaemon | None:
    """Validate enabled-email prerequisites and start its process-wide daemon."""
    if not _is_email_enabled():
        logger.info(
            "Email integration: disabled by system.channels.email.enabled -- skipping."
        )
        return None

    try:
        credential_path = validate_service_account_file()
        # Load synchronously so a missing migration or unavailable state store
        # aborts startup rather than failing later inside a background thread.
        load_gmail_watch_state()
    except Exception as exc:
        logger.critical("Email integration startup failed: %s", exc)
        raise

    logger.info(
        "Email integration: validated service-account credentials at %s",
        credential_path,
    )

    global _daemon
    with _daemon_lock:
        if _daemon is None:
            _daemon = EmailWatchDaemon(state_provider=load_gmail_watch_state)
        _daemon.start()
        return _daemon


def stop_email() -> None:
    with _daemon_lock:
        daemon = _daemon
    if daemon is not None:
        daemon.stop()
