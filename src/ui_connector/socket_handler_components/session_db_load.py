"""Building a Session from MySQL: settings only, from the cache, or full replay.

Three ways to load, from cheapest to most expensive:

  load_session_info_from_db  session-level state only (the session_meta row
      plus the newest event of each session-level type). No turns: the result
      has `turns_loaded=False` and can never be saved. For callers that only
      need the cwd, flags or settings (resume, skills info, file explorer).

  load_session_from_db, cache-compatible session  sealed turns come from
      `chat_history_cache` as stubs (one keyed range scan, no payloads); only
      the last two turns are replayed from their events, because the open turn
      and the most recent completed turn are the only ones a save can change.

  load_session_from_db, session not cached yet  the whole event log is
      replayed, as before v18, and a yellow warning asks the user to run
      `slbp intense-migration run fill-session-cache`.

Every load returns an independent Session object. The first load of a
session in this process also restores its per-process state (cwd, cost,
context usage) from session_meta (restore_cold_state).
"""

from __future__ import annotations

import logging
import threading
from typing import Iterator

from termcolor import colored

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.emit import _emit_backend_log
from src.utils.session_cache_projection import stub_turn_from_cache
from src.utils.session_events import (
    SESSION_LEVEL_EVENT_TYPES,
    ReplayState,
    normalize_payload,
    replay_events,
)
from src.utils.session_model import CURRENT_SCHEMA_VERSION, Session
from src.utils.session_schema_repair import repair_event_log
from src.utils.sql.chat_history_cache_db import (
    load_cached_history,
    load_last_turn_rows,
)
from src.utils.sql.session_store_db import (
    load_event_page,
    load_latest_event_rows,
    load_session_events,
    load_session_meta,
    mark_session_corrupt,
    max_event_id,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 500
FILL_SESSION_CACHE_COMMAND = "slbp intense-migration run fill-session-cache"

_warned_uncached: set[str] = set()
_warned_uncached_lock = threading.Lock()

# Sessions whose per-process state was restored by this process.
_restored: set[str] = set()
_restored_lock = threading.Lock()


def iter_event_rows(session_id: str, after: int, upto: int) -> Iterator[dict]:
    """Yield event rows with after < id <= upto, in id order, page by page."""
    while True:
        page = load_event_page(session_id, after, upto, _PAGE_SIZE)
        if not page:
            return
        yield from page
        after = page[-1]["id"]


def _replay_rows(state: ReplayState, rows) -> None:
    for row in rows:
        state.apply(row.get("event_type", ""), normalize_payload(row.get("payload")))


# ---------------------------------------------------------------------------
# Session-level state only
# ---------------------------------------------------------------------------


def load_session_info_from_db(session_id: str) -> Session | None:
    """Session-level state without turns, or None if there is no such session."""
    meta = load_session_meta(session_id)
    if meta is None:
        return None
    state = ReplayState(session_id)
    _replay_rows(state, load_latest_event_rows(session_id, SESSION_LEVEL_EVENT_TYPES))
    session = state.to_session()
    session.turns_loaded = False
    session.history_cache_compatible = bool(meta.get("history_cache_compatible"))
    _restore_once(session_id, meta, session.profile_name)
    return session


# ---------------------------------------------------------------------------
# Whole session
# ---------------------------------------------------------------------------


def load_session_from_db(session_id: str) -> Session | None:
    """Load a session for the agent (turns included), or None if absent."""
    # Database errors propagate: a failed read is a hard error, never a blank
    # session (saving that blank session would overwrite the real one).
    meta = load_session_meta(session_id)
    if meta is None:
        return None
    current_schema = meta.get("schema_version", 0) == CURRENT_SCHEMA_VERSION
    session = None
    if meta.get("history_cache_compatible") and current_schema:
        session = _session_from_cache(session_id)
    else:
        _warn_uncached(session_id)
    if session is None:
        session = _session_from_full_replay(session_id, meta)
        if session is None:
            return Session(session_id=session_id)
    if session.current_turn is not None and not _state.has_active_turn_task(session_id):
        # The server stopped in the middle of this turn. It stays exactly as
        # written (not completed); in memory it is just the latest closed turn,
        # which readers show as interrupted (conversation_history.py) and a
        # follow-up can reopen.
        session.completed_turns.append(session.current_turn)
        session.current_turn = None
    _restore_once(session_id, meta, session.profile_name)
    return session


def _session_from_cache(session_id: str) -> Session | None:
    """Sealed turns from the cache, the last two turns from their events.

    Returns None (the caller falls back to a full replay) if the cache does
    not cover every sealed turn, which would mean a bug in the cache writes.
    """
    tail = load_last_turn_rows(session_id, 2)
    state = ReplayState(session_id)
    if not tail:
        _replay_rows(
            state, load_latest_event_rows(session_id, SESSION_LEVEL_EVENT_TYPES)
        )
        session = state.to_session()
        session.history_cache_compatible = True
        return session

    first_tail_seq = tail[0]["turn_seq"]
    tail_start = tail[0]["start_event_id"]
    sealed = load_cached_history(session_id, first_tail_seq)
    if [row["turn_seq"] for row, _ in sealed] != list(range(1, first_tail_seq)):
        logger.error(
            "Chat history cache for session %s does not cover turns 1-%d; "
            "replaying the full event log instead.",
            session_id,
            first_tail_seq - 1,
        )
        return None

    # Session-level state as of the first tail turn, then the sealed turns,
    # then everything from the first tail turn on, in event order.
    _replay_rows(
        state,
        load_latest_event_rows(
            session_id, SESSION_LEVEL_EVENT_TYPES, upto_id=tail_start - 1
        ),
    )
    for turn_row, subturn_rows in sealed:
        state.add_sealed_turn(stub_turn_from_cache(turn_row, subturn_rows))
    _replay_rows(
        state, iter_event_rows(session_id, tail_start - 1, max_event_id(session_id))
    )
    session = state.to_session()
    session.history_cache_compatible = True
    return session


def _session_from_full_replay(session_id: str, meta: dict) -> Session | None:
    """Replay the whole event log (sessions whose cache is not built yet)."""
    rows = load_session_events(session_id)
    if meta.get("schema_version", 0) != CURRENT_SCHEMA_VERSION:
        # See session_schema_repair.py: a registered chain can rewrite
        # meta/rows forward to the current shape; if none is registered for
        # this version gap (the common case today), fall back to a blank
        # session rather than replaying a shape replay_events() was not
        # written to understand.
        repaired = repair_event_log(meta, rows, CURRENT_SCHEMA_VERSION)
        if repaired is None:
            return None
        meta, rows = repaired
    try:
        session = replay_events(session_id, rows)
    except Exception as exc:
        # The stored data itself is unreadable: flag it, never crash.
        logger.warning("Could not replay DB session %s: %s", session_id, exc)
        mark_session_corrupt(session_id)
        return None
    session.history_cache_compatible = False
    return session


def _warn_uncached(session_id: str) -> None:
    """Warn once per server run that a session is on the slow full-replay path."""
    with _warned_uncached_lock:
        if session_id in _warned_uncached:
            return
        _warned_uncached.add(session_id)
    message = (
        "This session's chat history cache has not been built, so it is loaded "
        "by replaying its whole event log (slow for long sessions). Stop the "
        f"server and run `{FILL_SESSION_CACHE_COMMAND}`."
    )
    logger.warning("Session %s: %s", session_id, message)
    _emit_backend_log(session_id, colored(message, "yellow", force_color=True))


# ---------------------------------------------------------------------------
# Cold-state restore
# ---------------------------------------------------------------------------


def _restore_once(session_id: str, meta: dict, profile_name: str | None) -> None:
    with _restored_lock:
        if session_id in _restored:
            return
        _restored.add(session_id)
    restore_cold_state(session_id, meta, profile_name)


def forget_restored_session(session_id: str) -> None:
    """A deleted session's per-process state is gone; restore it again if reused."""
    with _restored_lock:
        _restored.discard(session_id)


def restore_cold_state(session_id: str, meta: dict, profile_name: str | None) -> None:
    """Restore per-process state from session_meta on a session's first load.

    Later loads must not touch it: the in-process values are newer than
    session_meta between writes.
    """
    if meta.get("current_cwd"):
        _state._session_current_cwd[session_id] = meta["current_cwd"]
    if meta.get("total_cost_usd"):
        _state._session_costs[session_id] = float(meta["total_cost_usd"])
    if meta.get("last_context_usage"):
        last_context_usage = meta["last_context_usage"]
        # The snapshot is stamped with the profile that produced it. If the
        # profile changed between runs (e.g. switched after a restart), the
        # stored token counts and known_max_context no longer describe the
        # current profile — drop the stale snapshot instead of restoring it
        # (the next session write then stores NULL in session_meta, and the
        # next main-agent exchange with a max-context profile re-emits fresh).
        if last_context_usage.get("profile") == profile_name:
            # Runtime revisions intentionally restart with the server. No old
            # request can still be in flight on a session's first load in this
            # process, so rebase the
            # durable snapshot onto the new runtime generation.
            last_context_usage["profile_revision"] = 0
            _state._session_last_context_usage[session_id] = last_context_usage
        else:
            _state._session_last_context_usage.pop(session_id, None)
            logger.info(
                "Dropping stale last_context_usage for session %s "
                "(snapshot profile %r != current profile %r)",
                session_id,
                last_context_usage.get("profile"),
                profile_name,
            )
