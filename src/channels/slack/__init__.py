"""Slack channel integration.

Loads app-token and bot-token from the service_tokens table and
spins up a Slack Socket Mode client.  If startup fails for any reason,
the integration is silently disabled and the rest of the program
continues normally.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from src.utils.param_registry import param_storage_key as _param_storage_key
from src.utils.sql.kv_manager import KVManager
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


def _is_slack_enabled() -> bool:
    """Return True if the global param ``system.channels.slack.enabled`` is set to true.

    Defaults to False when the param is not set in the kv_store.
    """
    from src.data import get_pool

    try:
        pool = get_pool()
    except Exception as exc:
        logger.error("Slack: unable to get DB pool: %s", exc)
        return False

    with pool.get_connection() as conn:
        key = _param_storage_key("system.channels.slack.enabled")
        return bool(KVManager(conn).get_value(key, default=False))


def _handle_socket_request(client: SocketModeClient, request: SocketModeRequest) -> None:
    """Process an incoming Socket Mode request and log DM messages.

    Called by the Slack SDK's event loop for every envelope received
    over the WebSocket connection.  Non-DM messages are silently
    ignored.  The acknowledgment is sent automatically after this
    handler returns.
    """
    if request.type == "disconnect":
        logger.info("Slack: received disconnect request — reconnecting ...")
        return

    if request.type != "events_api":
        # Ignore interactive payloads, slash commands, etc. for now.
        return

    # Acknowledge immediately so Slack doesn't think we timed out.
    client.send_socket_mode_response(
        SocketModeResponse(envelope_id=request.envelope_id)
    )

    event: dict = request.payload.get("event", {})
    event_type: str | None = event.get("type")
    channel_type: str | None = event.get("channel_type")
    text: str = event.get("text", "")
    user: str | None = event.get("user")
    channel: str | None = event.get("channel")

    # Only handle message events.
    if event_type != "message":
        return

    # Reject messages from bots (including ourselves) to avoid echo loops.
    if event.get("bot_id") is not None:
        return

    # For now we only handle direct messages (channel_type == "im").
    if channel_type != "im":
        logger.info(
            "Slack: ignoring non-DM message (channel_type=%s, channel=%s, user=%s)",
            channel_type, channel, user,
        )
        return

    user_str = user or "unknown"
    channel_str = channel or "unknown"
    logger.info(
        "Slack DM received | user=%s channel=%s text=%s",
        user_str, channel_str, text,
        extra={"slack_user": user_str, "slack_channel": channel_str, "slack_dm_text": text},
    )


def startup_slack() -> None:
    """Bootstrap the Slack Socket Mode client.

    Call once during server startup.  All errors are caught and logged
    so that a broken Slack configuration never takes down the rest of
    the application.
    """
    # Check the global feature flag before doing anything else.
    if not _is_slack_enabled():
        logger.info(
            "Slack integration: disabled by system.channels.slack.enabled -- skipping."
        )
        return

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
    # Bootstrap the Socket Mode client in a background daemon thread.
    # ------------------------------------------------------------------
    try:
        client = SocketModeClient(
            app_token=app_token,
            web_client=WebClient(token=bot_token),
        )
    except Exception as exc:
        logger.error("Slack integration: failed to create SocketModeClient: %s", exc)
        return

    client.socket_mode_request_listeners.append(_handle_socket_request)

    try:
        thread = threading.Thread(
            target=client.connect,
            name="slack-socket-mode",
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        logger.error("Slack integration: failed to start Socket Mode thread: %s", exc)
        return

    logger.info("Slack integration: Socket Mode client connected (background thread).")
