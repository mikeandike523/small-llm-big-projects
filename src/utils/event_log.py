from __future__ import annotations

import json

import redis

# Events excluded from the replay log (too high-volume or not meaningful on replay)
REPLAY_EXCLUDED_EVENTS = {
    "token",
    "tool_result_chunk",
    "session_memory_keys_update",
    "session_memory_key_event",
    "backend_log",
}

_SESSION_EVENTS_TTL = 3600


def _stream_key(session_id: str) -> str:
    return f"session:{session_id}:events"


def log_event(r: redis.Redis, session_id: str, event_type: str, data: dict) -> str:
    """
    Append an event to the Redis Stream for this session.
    Returns the Redis Streams auto-generated ID (e.g. "1234567890123-0").
    """
    key = _stream_key(session_id)
    stream_id = r.xadd(key, {"type": event_type, "data": json.dumps(data)})
    r.expire(key, _SESSION_EVENTS_TTL)
    return stream_id  # type: ignore[return-value]


def get_events_since(r: redis.Redis, session_id: str, last_id: str) -> list[dict]:
    """
    Return all events after last_id (exclusive).
    last_id should be a Redis Stream ID like "1234567890123-0" or "0-0" for all events.
    Returns list of dicts: [{id, type, data: dict}, ...].
    """
    key = _stream_key(session_id)
    # XRANGE with exclusive start requires "(" prefix — use the helper below.
    # If last_id is "0-0" we want everything, so use "0" as the start.
    if last_id in ("0-0", "0"):
        start = "0"
    else:
        # Redis Streams exclusive range: "(id" syntax (redis-py supports this)
        start = f"({last_id}"

    try:
        entries = r.xrange(key, min=start, max="+")
    except redis.ResponseError:
        return []

    result = []
    for entry_id, fields in entries:
        try:
            data = json.loads(fields.get("data", "{}"))
        except (json.JSONDecodeError, TypeError):
            data = {}
        result.append(
            {
                "id": entry_id,
                "type": fields.get("type", ""),
                "data": data,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Bookmark ("watermark") linking this log to the durable MySQL event log
# ---------------------------------------------------------------------------
#
# The agent loop's step-boundary saves record the id of the latest logged event
# at save time: everything up to it is described by state now in MySQL. A page
# load rebuilds history from MySQL and replays only the events after it.


def watermark_key(session_id: str) -> str:
    return f"session:{session_id}:events_watermark"


def latest_stream_id(r: redis.Redis, session_id: str) -> str | None:
    """Return the id of the newest logged event, or None if the log is empty."""
    try:
        entries = r.xrevrange(_stream_key(session_id), count=1)
    except redis.ResponseError:
        return None
    return entries[0][0] if entries else None


def get_watermark(r: redis.Redis, session_id: str) -> str:
    """Return the bookmark, or "0-0" (replay the whole log) when unset."""
    return r.get(watermark_key(session_id)) or "0-0"


def set_watermark(r: redis.Redis, session_id: str, stream_id: str, ttl: int) -> None:
    r.setex(watermark_key(session_id), ttl, stream_id)


def trim_stream_upto(r: redis.Redis, session_id: str, stream_id: str) -> None:
    """Drop logged events older than `stream_id` (they are durable in MySQL).

    XTRIM MINID keeps `stream_id` itself; get_events_since() excludes it.
    """
    try:
        r.xtrim(_stream_key(session_id), minid=stream_id)
    except redis.ResponseError:
        pass
