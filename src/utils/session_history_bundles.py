"""Assemble per-turn history bundles from a session's event log, streaming.

The history loader reads `session_events` page by page (in `id` order) and
needs each turn as soon as it is finished, without ever holding the whole
session. Two facts make that possible:

  * Every turn has exactly one `turn_started` event, and the loader fetches the
    list of them up front. Only the most recent completed turn can be reopened
    by a follow-up, so once turn N+1 has started, turn N can never change again:
    turn N's events lie in [start_N, start_N+1).
  * `exchange_recorded` / `subturn_summary_set` carry only a subturn id, which
    `subturn_started` maps to its turn.

Events are folded with the normal reducer (`ReplayState`), so a bundle is
exactly `turn_to_dict` of the turn a full `replay_events` would produce. A
finished turn is popped from the state, keeping memory bounded to one turn.
Session-level events (todo list, profile, approval mode, ...) fold into the
state's Session as usual.
"""

from __future__ import annotations

import logging

from src.utils.session_events import (
    EVT_EXCHANGE_RECORDED,
    EVT_SKILLS_SELECTED,
    EVT_SUBTURN_STARTED,
    EVT_SUBTURN_SUMMARY_SET,
    EVT_TITLE_SET,
    EVT_TURN_COMPLETED,
    EVT_TURN_REOPENED,
    EVT_TURN_STARTED,
    ReplayState,
    normalize_payload,
)
from src.utils.session_model import turn_to_dict

logger = logging.getLogger(__name__)

_TURN_EVENTS = frozenset(
    {
        EVT_TURN_STARTED,
        EVT_TITLE_SET,
        EVT_SKILLS_SELECTED,
        EVT_SUBTURN_STARTED,
        EVT_TURN_COMPLETED,
        EVT_TURN_REOPENED,
    }
)
_SUBTURN_EVENTS = frozenset({EVT_EXCHANGE_RECORDED, EVT_SUBTURN_SUMMARY_SET})


class TurnBundleAssembler:
    """Fold ordered event rows into finished per-turn dicts.

    `turn_starts` is `[(turn_started event id, turn_id), ...]` in id order and
    must cover every turn whose events will be fed. Rows are
    `{"id", "event_type", "payload"}` in id order. `feed()` and `finish()`
    return the turns completed by that call, in turn order.
    """

    def __init__(self, session_id: str, turn_starts: list[tuple[int, str]]) -> None:
        self.session_id = session_id
        self._state = ReplayState(session_id)
        self._starts = turn_starts
        self._next_start = 0
        self._open_turn: str | None = None
        self._sealed: set[str] = set()
        self._subturn_turn: dict[str, str] = {}
        self.sent_turn_ids: list[str] = []
        self.warnings: list[str] = []

    @property
    def todo_list(self) -> list:
        """The session-level live todo list as of the last fed event."""
        return self._state.session.session_data.get("todo_list") or []

    def feed(self, row: dict) -> list[dict]:
        done: list[dict] = []
        event_id = int(row["id"])
        while (
            self._next_start < len(self._starts)
            and event_id >= self._starts[self._next_start][0]
        ):
            if self._open_turn is not None:
                done.extend(self._seal(self._open_turn))
            self._open_turn = self._starts[self._next_start][1]
            self._next_start += 1

        event_type = row.get("event_type", "")
        payload = normalize_payload(row.get("payload"))
        if not self._accepts(event_id, event_type, payload):
            return done
        if event_type == EVT_SUBTURN_STARTED and payload.get("subturn_id"):
            self._subturn_turn[payload["subturn_id"]] = payload.get("turn_id")
        self._state.apply(event_type, payload)
        return done

    def finish(self) -> list[dict]:
        done = self._seal(self._open_turn) if self._open_turn is not None else []
        self._open_turn = None
        expected = [turn_id for _, turn_id in self._starts]
        if self.sent_turn_ids != expected:
            self._warn(
                f"bundled turns {self.sent_turn_ids} do not match turn list {expected}"
            )
        return done

    def _accepts(self, event_id: int, event_type: str, payload: dict) -> bool:
        if event_type in _SUBTURN_EVENTS:
            subturn_id = payload.get("subturn_id")
            turn_id = self._subturn_turn.get(subturn_id)
            if turn_id is None:
                self._warn(f"event {event_id} ({event_type}) has unknown subturn")
                return False
        elif event_type in _TURN_EVENTS:
            turn_id = payload.get("turn_id")
        else:
            return True  # session-level event
        if turn_id in self._sealed:
            self._warn(f"event {event_id} ({event_type}) for already-sent turn")
            return False
        if turn_id != self._open_turn:
            self._warn(f"event {event_id} ({event_type}) is outside its turn's range")
            return False
        return True

    def _seal(self, turn_id: str) -> list[dict]:
        turn = self._state.pop_turn(turn_id)
        self._sealed.add(turn_id)
        if turn is None:
            self._warn(f"turn {turn_id} has no events")
            return []
        for st in turn.subturns:
            self._subturn_turn.pop(st.id, None)
        self.sent_turn_ids.append(turn_id)
        return [turn_to_dict(turn)]

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning("History bundles for session %s: %s", self.session_id, message)
