"""Webhook hit log for the email debug page.

The gateway proxy (proxy-server/webhookRecorder.js) records every
``/webhooks/**`` request into Redis, including ones Flask never answered.
This module serves that log and relays new hits from the Redis pub/sub
channel to the ``email-webhook-debug`` socket.io room.

Runs whether or not the email channel is enabled: a disabled channel answers
404, which is exactly the kind of thing this view should reveal.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid

from flask import jsonify, request
from flask_socketio import join_room, leave_room

from src.ui_connector.app import app, socketio
from src.ui_connector.socket_handler_components.state import _get_redis

logger = logging.getLogger(__name__)

HITS_KEY = "slbp:email:webhook_hits"
LIVE_CHANNEL = "slbp:email:webhook_hits:live"
ROOM = "email-webhook-debug"
HIT_EVENT = "email_webhook_hit"
MAX_HITS = 500
RECONNECT_DELAY_SECONDS = 5.0

_relay_lock = threading.Lock()
_relay_stop: threading.Event | None = None
_relay_thread: threading.Thread | None = None


def list_webhook_hits(limit: int = MAX_HITS) -> list[dict]:
    """Newest first."""
    limit = max(1, min(int(limit), MAX_HITS))
    hits = []
    for raw in _get_redis().lrange(HITS_KEY, 0, limit - 1):
        try:
            hits.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("Skipping unparseable webhook hit record")
    return hits


@app.get("/api/email/webhook-hits")
def email_webhook_hits():
    try:
        limit = int(request.args.get("limit", str(MAX_HITS)))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    return jsonify(hits=list_webhook_hits(limit))


@socketio.on("email_webhook_debug_join")
def handle_email_webhook_debug_join(_data=None):
    join_room(ROOM)
    return {"ok": True}


@socketio.on("email_webhook_debug_leave")
def handle_email_webhook_debug_leave(_data=None):
    leave_room(ROOM)
    return {"ok": True}


def _relay_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        pubsub = None
        try:
            pubsub = _get_redis().pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(LIVE_CHANNEL)
            while not stop.is_set():
                message = pubsub.get_message(timeout=1.0)
                if message is None or message.get("type") != "message":
                    continue
                try:
                    hit = json.loads(message["data"])
                except (TypeError, json.JSONDecodeError):
                    logger.warning("Skipping unparseable live webhook hit")
                    continue
                socketio.emit(HIT_EVENT, hit, to=ROOM)
        except Exception:
            logger.exception(
                "Webhook hit relay lost Redis; retrying in %.0fs",
                RECONNECT_DELAY_SECONDS,
            )
            stop.wait(RECONNECT_DELAY_SECONDS)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass


def start_webhook_debug_relay() -> None:
    global _relay_stop, _relay_thread
    with _relay_lock:
        if _relay_thread is not None and _relay_thread.is_alive():
            return
        _relay_stop = threading.Event()
        _relay_thread = threading.Thread(
            target=_relay_loop,
            args=(_relay_stop,),
            name=f"email-webhook-relay-{uuid.uuid4()}",
            daemon=True,
        )
        _relay_thread.start()
    logger.info("Email webhook hit relay started (room=%s)", ROOM)


def stop_webhook_debug_relay(timeout: float = 3.0) -> None:
    global _relay_stop, _relay_thread
    with _relay_lock:
        stop, thread = _relay_stop, _relay_thread
        _relay_stop = _relay_thread = None
    if stop is not None:
        stop.set()
    if thread is not None:
        thread.join(timeout=timeout)
