# Progressive Exchange Hashing in the Save Path

Status: idea, not started (written 2026-10-23, after the chat history cache
work in `46ede61` / `37c0b69`).

## Background

`_save_session` runs several times per agent step (after each exchange is
appended, after titles, at turn end). It finds what to persist by diffing the
in-memory `Session` against the persist cursor in
`compute_events` (`src/ui_connector/socket_handler_components/_session_event_emit.py`).

Since the chat history cache change, `compute_events` only looks at the
**persist window**, the last two turns (`persist_window`). Inside that window
it still does this on every save, for every subturn and every exchange:

```python
for idx, ex in enumerate(st.exchanges):
    h = exchange_hash(ex)   # json.dumps(exchange_payload(ex), sort_keys=True) + sha1
    ...compare with cursor["turns"][turn]["subturns"][st]["exchange_hashes"][idx]
```

`exchange_payload` includes every tool call's arguments and **full result**,
plus `reasoning_native`. So one save costs about the total serialized size of
every exchange in the window, and a turn of N steps costs O(N^2 x exchange
size) over its lifetime.

### Why this is usually fine

The turn/subturn design keeps this small on purpose. A new task starts a new
turn, and closed subturns only send their final answer plus Context Notes to
the model, so the live part of the conversation stays short. The re-hash cost
grows with the length of the **current turn**, not the session.

It only matters for a long single turn: hundreds of tool steps, or large tool
results (file reads, web pages) in the same turn. Long-horizon tasks are the
case where that could start to happen.

## Step 0: Measure first

Before changing anything, time `compute_events` and log it to the backend log
when it exceeds a threshold, along with the window's exchange count and payload
bytes. If even a long real turn stays in the low milliseconds, stop here: the
MySQL round trip of the same save is already bigger.

## Options

### A. Skip frozen subturns (safe, small)

Only the **last subturn** of the open turn can gain or change exchanges.
Earlier subturns of the same turn are closed: a follow-up appends a new
subturn and never edits an older one's exchanges. Their `detailed_summary`
can still be set later, but that is compared as a plain string and is not part
of the hash.

So, mark a subturn's cursor entry `"sealed": true` once a later subturn exists
and the sealed subturn has been hashed once. Then skip its exchange loop
entirely. That removes the "follow-ups multiply the cost" factor, with no
change to how exchanges are hashed.

### B. Hash only the tail of the live subturn (the main win)

Within the live subturn, exchanges are appended **complete**. In
`agent_loop.py` the exchange is filled (content, tool calls, results,
reasoning, usage) and then `current_subturn.exchanges.append(exchange)`, then
`_save_session`. If an exchange can no longer change once a later exchange
exists, each save only needs to hash:

- the exchanges added since the last save (`idx >= len(hashes)`), and
- the **last previously-hashed exchange** (it may still get late fields such
  as `user_continuation` or a repaired final answer).

That makes each save O(new exchanges), so a whole turn is O(N). The cursor
already stores `exchange_hashes`, so no new storage is needed. The loop simply
starts at `max(0, len(hashes) - 1)` instead of 0.

**Required audit before doing this.** Every place that mutates an exchange
other than the last one in its subturn must be found. Candidates to check:

- `tool_execution.py`: `tool_record.result = ...` and
  `exchange.tool_calls.append(...)`. These must only happen before the
  exchange is appended, or on the last exchange.
- The patch rewrite watchdog (rewrites a failing `apply_patch` call's args).
- Stop & Redirect / Try Again (`project_stop_redirect`): do they edit or
  truncate earlier exchanges?
- `repair_incomplete_turn` (`session_model.py`): fills interrupted tool
  results and appends a final marker on the open turn after a restart.
- Heartbeat continuations and anything that sets `user_continuation`.

If any of these edits an older exchange, either move the edit to an append,
or have that code path call a small `mark_exchange_changed(subturn, idx)` that
drops `hashes[idx:]` so the next save re-hashes from there.

### C. Explicit change tracking on the model (more invasive)

Give `LLMExchange` / `ToolCallRecord` a revision counter, bumped by
`__setattr__` and by a wrapped `tool_calls` list. Cache `(revision, hash)` on
the object (not in the cursor) and re-hash only when the revision moved.

This is exact even for edits to old exchanges, but it touches the core
dataclasses, and in-place list or dict mutation inside `args` or
`reasoning_native` would still slip past it unless those are wrapped too. It
is too much machinery for this problem; prefer B plus the audit.

### D. Cheaper fingerprint instead of sha1 of the full JSON (not recommended)

Fingerprint by lengths and counts (content length, tool-call count, filled
results, `is_final`). It is fast, but it misses a same-length edit, which
would silently drop an update from MySQL. Correctness of the event log matters
more than this speed-up.

## Recommendation

1. Step 0: measure. Only continue if real long turns show it.
2. Option A: skip sealed subturns. Safe on its own.
3. Option B: hash only the tail exchanges, after the audit above. Add a
   test-only verifier that, in the test suite (or behind a debug param),
   re-hashes the whole window after each save and asserts that nothing was
   missed.

Keep the hashes where they are (the Redis persist cursor). The cursor is small
again now that it only covers the persist window, so it does not need to move
into process memory, and keeping it in Redis preserves today's behaviour where
a different `Session` copy can save next.

## Tests to add

- A long synthetic turn (for example 300 exchanges with large tool results):
  the number of `exchange_hash` calls per save stays constant (patch
  `exchange_hash` with a counter).
- Every mutation site found in the audit: a change made after the exchange
  was first saved is still persisted (event replay equals the in-memory
  session). The existing `_EventLog` helpers in
  `tests/test_session_history_bundles.py` and `tests/test_chat_history_cache.py`
  already do the replay comparison.
