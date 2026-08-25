"""
Registry for repairing sessions whose stored schema_version predates the
running code's CURRENT_SCHEMA_VERSION.

Why this exists: CURRENT_SCHEMA_VERSION (session_model.py) is a hard equality
gate in session_store.py, not an informational marker. A session whose stored
schema_version doesn't match it is silently replaced with a blank Session --
same ID, no history, no error -- rather than migrated (see
project_reasoning_native_dialects.md in memory for how this was discovered:
a purely-additive field got a version bump it didn't need, which would have
blanked every existing session). That's an acceptable outcome for a change
you genuinely want to invalidate old sessions for, but wasteful for any bump
where old data COULD be adapted forward instead. This module is where that
adaptation goes, so a future schema bump doesn't have to mean discarding
every session that predates it.

Nothing is registered here yet -- no schema bump past v5 has needed a repair.
When you next bump CURRENT_SCHEMA_VERSION for a change that isn't purely
additive (a renamed field, a restructured nested shape, a changed meaning of
an existing field -- as opposed to a new optional field defaulted via
`.get(key, default)`, which needs neither a version bump nor a repairer),
write and register a repairer for that step *before* bumping the constant.
Register it for the version pair you're introducing, e.g.:

    register_schema_repair(6, 7, _repair_v6_to_v7)
    register_event_log_repair(6, 7, _repair_event_log_v6_to_v7)

Two separate repair surfaces exist because the two load paths in
session_store.py hold genuinely different raw shapes at the point they check
schema_version, and repair has to run on the *raw*, undeserialized data --
by the time you have a constructed Session object, any renamed/restructured
field has already been read under its new (wrong, for old data) key by
session_from_dict()/replay_events() and the old value is gone:

  - The Redis warm-cache path (`_load_session`) holds one flat dict -- the
    exact shape session_to_dict() produces and session_from_dict() consumes.
    register_schema_repair() / repair_session_dict() cover this.

  - The durable MySQL path (`_session_from_db`) holds `meta` (the
    session_meta row) plus `rows`, the session's append-only event log --
    each row `{"event_type": str, "payload": dict}` in replay order, exactly
    as load_session_events() returns them and replay_events() consumes them.
    register_event_log_repair() / repair_event_log() cover this. A repairer
    here rewrites `meta` and/or individual event payloads (e.g. renaming a
    key inside an `exchange_recorded` payload) so that replay_events() reads
    the current shape.

Repair functions should be pure and defensive: a single step only needs to
bridge from_version -> from_version + 1 (usually to_version = from_version+1)
and shouldn't assume every key from the old version is present. Chains of
single steps are composed automatically to bridge multi-version gaps -- e.g.
registering (5, 6) and (6, 7) lets a v5 session reach v7 without a (5, 7)
entry. If a step in a requested chain is missing, resolution fails and the
caller falls back to its existing "can't load this" behavior (today: a blank
Session) -- this module never invents data or guesses.
"""

from __future__ import annotations

from typing import Callable

SessionDictRepairFn = Callable[[dict], dict]
EventLogRepairFn = Callable[[dict, list[dict]], tuple[dict, list[dict]]]

_SESSION_DICT_REPAIRERS: dict[tuple[int, int], SessionDictRepairFn] = {}
_EVENT_LOG_REPAIRERS: dict[tuple[int, int], EventLogRepairFn] = {}


def register_schema_repair(from_version: int, to_version: int, fn: SessionDictRepairFn) -> None:
    """
    Register a single-step repair for the Redis warm-cache path's flat
    session dict: from_version -> to_version (normally to_version ==
    from_version + 1). fn receives a dict in the from_version shape and must
    return a new dict in the to_version shape.
    """
    _SESSION_DICT_REPAIRERS[(from_version, to_version)] = fn


def register_event_log_repair(from_version: int, to_version: int, fn: EventLogRepairFn) -> None:
    """
    Register a single-step repair for the durable MySQL path: from_version ->
    to_version. fn receives (meta, rows) in the from_version shape and must
    return (meta, rows) in the to_version shape, ready for the next
    registered step or, if to_version is CURRENT_SCHEMA_VERSION, for
    replay_events().
    """
    _EVENT_LOG_REPAIRERS[(from_version, to_version)] = fn


def _resolve_chain(registry: dict[tuple[int, int], Callable], from_version: int, to_version: int):
    """Shared chain-walk: compose registered single steps from_version -> to_version."""
    if from_version == to_version:
        return []
    chain: list[Callable] = []
    version = from_version
    seen = {version}
    while version != to_version:
        step = next(
            ((end, fn) for (start, end), fn in registry.items() if start == version),
            None,
        )
        if step is None or step[0] in seen:
            return None
        chain.append(step[1])
        version, _ = step
        seen.add(version)
    return chain


def repair_session_dict(d: dict, current_version: int) -> dict | None:
    """
    Attempt to repair a raw session dict (the shape session_to_dict()
    produces / session_from_dict() consumes) from whatever schema_version it
    carries up to current_version. Returns the repaired dict on a complete
    chain, or None if no complete chain is registered -- nothing was
    modified, and the caller decides the fallback.
    """
    chain = _resolve_chain(_SESSION_DICT_REPAIRERS, d.get("schema_version", 0), current_version)
    if chain is None:
        return None
    repaired = d
    for step_fn in chain:
        repaired = step_fn(repaired)
    return repaired


def repair_event_log(
    meta: dict, rows: list[dict], current_version: int
) -> tuple[dict, list[dict]] | None:
    """
    Attempt to repair a session's durable (meta, rows) pair from whatever
    schema_version `meta` carries up to current_version. Returns the
    repaired (meta, rows) on a complete chain, or None if no complete chain
    is registered -- nothing was modified, and the caller decides the
    fallback.
    """
    chain = _resolve_chain(_EVENT_LOG_REPAIRERS, meta.get("schema_version", 0), current_version)
    if chain is None:
        return None
    repaired_meta, repaired_rows = meta, rows
    for step_fn in chain:
        repaired_meta, repaired_rows = step_fn(repaired_meta, repaired_rows)
    return repaired_meta, repaired_rows
