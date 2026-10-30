"""Email channel startup and lifecycle integration."""

from __future__ import annotations

import logging
import threading

from src.channels.email.config import EmailConfig, load_email_config
from src.channels.email.credentials import validate_service_account_file
from src.channels.email.gmail_client import build_gmail_client
from src.channels.email.state import ensure_mailbox_state, load_mailbox_state
from src.channels.email.watch_daemon import EmailWatchDaemon
from src.utils.param_helper import get_param_value
from src.utils.sql.kv_manager import KVManager

logger = logging.getLogger(__name__)

_daemon_lock = threading.Lock()
_daemon: EmailWatchDaemon | None = None
_config: EmailConfig | None = None


def is_email_enabled() -> bool:
    from src.data import get_pool

    pool = get_pool()
    with pool.get_connection() as conn:
        return bool(get_param_value(KVManager(conn), "system.channels.email.enabled"))


def get_email_config() -> EmailConfig | None:
    """Return validated runtime configuration, or none when not started."""
    return _config


def startup_email() -> EmailWatchDaemon | None:
    """Validate enabled-email prerequisites and start its process-wide daemon."""
    if not is_email_enabled():
        logger.info(
            "Email integration: disabled by system.channels.email.enabled -- "
            "skipping credential validation and daemon startup."
        )
        return None

    try:
        config = load_email_config()
        credential_path = validate_service_account_file(config)
        ensure_mailbox_state(config.mailbox_email)
        load_mailbox_state(config.mailbox_email)
    except Exception as exc:
        logger.critical("Email integration startup failed: %s", exc, exc_info=True)
        raise

    logger.info(
        "Email integration validated: mailbox=%s alias=%s credentials=%s",
        config.mailbox_email,
        config.alias_email,
        credential_path,
    )

    global _daemon, _config
    with _daemon_lock:
        _config = config
        if _daemon is None:
            _daemon = EmailWatchDaemon(
                config=config,
                gmail_factory=lambda: build_gmail_client(config),
            )
        _daemon.start()
        return _daemon


def notify_email_work() -> None:
    with _daemon_lock:
        daemon = _daemon
    if daemon is not None:
        daemon.notify()


def stop_email() -> None:
    global _daemon, _config
    with _daemon_lock:
        daemon = _daemon
        _daemon = None
        _config = None
    if daemon is not None:
        daemon.stop()
