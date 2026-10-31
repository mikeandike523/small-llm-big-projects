"""Webhook hit log served from Redis and relayed to the socket.io room."""

from __future__ import annotations

import json
import threading

import src.channels.email.webhook_debug as debug_module
from src.ui_connector.app import app


class FakePubSub:
    def __init__(self, messages, stop: threading.Event):
        self._messages = list(messages)
        self._stop = stop
        self.subscribed = []
        self.closed = False

    def subscribe(self, channel):
        self.subscribed.append(channel)

    def get_message(self, timeout):
        if self._messages:
            return self._messages.pop(0)
        self._stop.set()
        return None

    def close(self):
        self.closed = True


class FakeRedis:
    def __init__(self, stored=(), pubsub=None):
        self.stored = list(stored)
        self._pubsub = pubsub

    def lrange(self, key, start, end):
        assert key == debug_module.HITS_KEY
        return self.stored[start : end + 1]

    def pubsub(self, ignore_subscribe_messages):
        return self._pubsub


def test_hits_route_returns_newest_first_and_skips_garbage(monkeypatch) -> None:
    stored = [json.dumps({"id": "b"}), "not json", json.dumps({"id": "a"})]
    monkeypatch.setattr(debug_module, "_get_redis", lambda: FakeRedis(stored))
    response = app.test_client().get("/api/email/webhook-hits?limit=10")
    assert response.status_code == 200
    assert [hit["id"] for hit in response.get_json()["hits"]] == ["b", "a"]


def test_relay_emits_live_hits_to_room(monkeypatch) -> None:
    stop = threading.Event()
    pubsub = FakePubSub(
        [
            {"type": "message", "data": json.dumps({"id": "x", "status": 502})},
            {"type": "message", "data": "garbage"},
        ],
        stop,
    )
    monkeypatch.setattr(debug_module, "_get_redis", lambda: FakeRedis(pubsub=pubsub))
    emitted = []
    monkeypatch.setattr(
        debug_module.socketio,
        "emit",
        lambda event, data, to: emitted.append((event, data, to)),
    )
    debug_module._relay_loop(stop)
    assert pubsub.subscribed == [debug_module.LIVE_CHANNEL]
    assert emitted == [
        (debug_module.HIT_EVENT, {"id": "x", "status": 502}, debug_module.ROOM)
    ]
    assert pubsub.closed
