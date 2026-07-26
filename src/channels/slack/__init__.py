"""Slack channel integration.

Loads app-token and bot-token from the service_tokens table and
spins up a Slack Socket Mode client.  If startup fails for any reason,
the integration is silently disabled and the rest of the program
continues normally.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _load_slack_tokens() -> tuple[Optional[str], Optional[str]]:
    """Return (app_token, bot_token) from the service_tokens table.

    Returns (None, None) when tokens cannot be loaded so the caller
    can treat every failure as "slack unavailable".
    """
    from src.data import get_pool

    try:
        pool = get_pool()
    except Exception as exc:
        logger.error("Slack: unable to get DB pool: %s", exc)
        return None, None

    sql = """
        SELECT name, value
        FROM service_tokens
        WHERE provider = %s
          AND name IN (%s, %s)
    """

    try:
        with pool.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, ("slack", "app-token", "bot-token"))
                rows = cur.fetchall()
    except Exception as exc:
        logger.error("Slack: failed to query service_tokens: %s", exc)
        return None, None

    tokens: dict[str, str] = {}
    for name, value in rows:
        tokens[name] = str(value)

    app_token = tokens.get("app-token")
    bot_token = tokens.get("bot-token")

    if not app_token:
        logger.error(
            "Slack: no 'app-token' found in service_tokens for provider 'slack'. "
            "Set one with: slbp service-token set slack app-token <xapp-...>"
        )
    if not bot_token:
        logger.error(
            "Slack: no 'bot-token' found in service_tokens for provider 'slack'. "
            "Set one with: slbp service-token set slack bot-token <xoxb-...>"
        )

    return app_token, bot_token


def startup_slack() -> None:
    """Bootstrap the Slack Socket Mode client.

    Call once during server startup.  All errors are caught and logged
    so that a broken Slack configuration never takes down the rest of
    the application.
    """
    logger.info("Slack integration: starting up …")

    try:
        app_token, bot_token = _load_slack_tokens()
    except Exception as exc:
        logger.error("Slack integration: unexpected error loading tokens: %s", exc)
        return

    if not app_token or not bot_token:
        logger.warning(
            "Slack integration: missing one or both tokens -- Slack support is disabled."
        )
        return

    # ------------------------------------------------------------------
    # TODO: bootstrap Slack Socket Mode client here using app_token and
    #       bot_token (future step).
    # ------------------------------------------------------------------

    logger.info("Slack integration: ready (stub -- Socket Mode not yet wired).")