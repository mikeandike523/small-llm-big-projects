"""Authenticated Google Pub/Sub push endpoint for Gmail notifications."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from flask import jsonify, request

from src.channels.email import get_email_config, notify_email_work
from src.channels.email.notification_store import (
    GmailNotification,
    enqueue_notification,
)
from src.ui_connector.app import app

logger = logging.getLogger(__name__)
MAX_PUSH_BYTES = 256 * 1024
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class PushAuthenticationError(RuntimeError):
    """An authenticated push identity was missing or unacceptable."""


def _bearer_token() -> str:
    value = request.headers.get("Authorization", "")
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise PushAuthenticationError("missing Bearer authorization")
    return token.strip()


def verify_push_identity(token: str, audience: str) -> dict[str, Any]:
    """Use google-auth's cached public-key verification, not custom crypto."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, Request(), audience=audience)


def _authenticate(config) -> dict[str, Any]:
    try:
        claims = verify_push_identity(_bearer_token(), config.push_audience)
    except PushAuthenticationError:
        raise
    except Exception as exc:
        raise PushAuthenticationError("Google token verification failed") from exc
    issuer = str(claims.get("iss") or "")
    verified = claims.get("email_verified")
    email_verified = verified is True or str(verified).casefold() == "true"
    identity = str(claims.get("email") or "")
    if issuer not in GOOGLE_ISSUERS:
        raise PushAuthenticationError("token issuer is not Google")
    if not email_verified:
        raise PushAuthenticationError("token email is not verified")
    if identity.casefold() != config.push_service_account_email.casefold():
        raise PermissionError("token email is not the configured push identity")
    return claims


def _decode_notification(payload: dict, config) -> GmailNotification:
    message = payload.get("message")
    subscription = str(payload.get("subscription") or "")
    if not isinstance(message, dict):
        raise TypeError("Pub/Sub envelope is missing message")
    if subscription != config.subscription_resource:
        raise PermissionError("unexpected Pub/Sub subscription resource")
    pubsub_id = str(message.get("messageId") or message.get("message_id") or "")
    encoded = message.get("data")
    if not pubsub_id or not isinstance(encoded, str):
        raise ValueError("Pub/Sub messageId or data is missing")
    try:
        decoded = base64.b64decode(encoded, validate=True)
        gmail_notice = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Pub/Sub data is not valid base64-encoded JSON") from exc
    mailbox = str(gmail_notice.get("emailAddress") or "")
    history_id = str(gmail_notice.get("historyId") or "")
    if mailbox.casefold() != config.mailbox_email.casefold():
        raise PermissionError("notification mailbox is not configured")
    if not history_id.isdigit():
        raise ValueError("notification historyId is invalid")
    return GmailNotification(
        pubsub_message_id=pubsub_id,
        subscription_resource=subscription,
        mailbox_email=config.mailbox_email,
        notified_history_id=history_id,
    )


@app.post("/webhooks/gmail")
def gmail_webhook():
    """Verify, durably enqueue, then acknowledge a wrapped Pub/Sub push."""
    config = get_email_config()
    if config is None:
        return jsonify(error="email channel is disabled or unavailable"), 404
    if request.content_length is not None and request.content_length > MAX_PUSH_BYTES:
        return jsonify(error="request body is too large"), 413
    try:
        claims = _authenticate(config)
        raw_body = request.get_data(cache=False)
        if len(raw_body) > MAX_PUSH_BYTES:
            return jsonify(error="request body is too large"), 413
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("Pub/Sub envelope must be a JSON object")
        notification = _decode_notification(payload, config)
        inserted = enqueue_notification(notification)
    except PushAuthenticationError as exc:
        logger.warning("Rejected unauthenticated Gmail push: %s", exc)
        return jsonify(error="unauthorized"), 401
    except PermissionError as exc:
        logger.warning("Rejected unauthorized Gmail push: %s", exc)
        return jsonify(error="forbidden"), 403
    except (ValueError, TypeError) as exc:
        logger.warning("Rejected malformed Gmail push: %s", exc)
        return jsonify(error="invalid Pub/Sub envelope"), 400
    except Exception:
        logger.exception("Gmail push could not be durably persisted")
        return jsonify(error="notification persistence unavailable"), 503

    logger.info(
        "Accepted Gmail push: pubsub_message_id=%s history_id=%s "
        "identity=%s inserted=%s",
        notification.pubsub_message_id,
        notification.notified_history_id,
        claims.get("email"),
        inserted,
    )
    notify_email_work()
    return "", 204
