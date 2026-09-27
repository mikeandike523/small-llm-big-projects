# Hardening the Event Flow for Heartbeats and Live UI Sessions

> **Status: PARTIAL (2026-09-26).** Items 5 and 6 are done (see their notes).
> Everything else is notes only; the current system is being kept as-is. Nothing here breaks the history sent to the model; the items are
> about accuracy of that history, the UI recovering after a gap, and
> heartbeat-started turns and human users sharing one session cleanly.

## Background: Two Event Logs

A session has two separate event logs. Most items below come from mixing them
up.

| | MySQL `session_events` | Redis stream `session:{id}:events` |
|---|---|---|
| Records | The conversation *model*: `session_created`, `turn_started`, `subturn_started`, `exchange_recorded`, `subturn_summary_set`, `turn_completed`, title, skills, todo list, approval mode, profile, heartbeat settings | UI socket events: `turn_start`, `tool_call`, `tool_result`, `approval_request`, `approval_resolved`, `error`, … |
| Lifetime | Permanent | TTL 1 hour (`event_log._SESSION_EVENTS_TTL`), refreshed only when a new event is logged |
| Used for | Rebuilding the `Session` and the model payload | Catching a (re)connecting browser up via `resume_session` → `event_replay` |

Not in either log: streamed tokens, `tool_result_chunk`, `backend_log`,
session-memory key events (`REPLAY_EXCLUDED_EVENTS`), and the pending approval
itself (`_state._pending_approvals`, process memory only).

**Save granularity.** A step (one assistant reply plus all its tool calls
and results) is persisted as one `exchange_recorded` only after
`_execute_tools` returns (`agent_loop.py`, `current_subturn.exchanges.append`
then `_save_session`). Nothing about an in-progress step is durable.

**What is already safe.** Because a step is saved atomically, the durable
history never contains a tool call without a result. Cancel/crash mid-step
drops the whole step and appends a marker exchange; on a cold load after a
crash, `repair_incomplete_turn` pairs any dangling calls and closes the turn.
A lost `approval_request` event therefore never corrupts history — approvals
only appear in history through the tool result they produce.

## Known Gaps

### 1. Pending approval invisible after 1 hour (UI recovery)

A turn waiting on `wait-for-human` logs no new events, so the Redis stream
(including `approval_request`) expires an hour later. Opening the session then
shows the turn as active (`isTurnActive`) but no dialog. The backend is still
waiting correctly; only the UI lost the request.

- Common with heartbeats: an overnight heartbeat under `wait-for-human` will
  almost always wait more than an hour.
- Current workaround: press Stop. `cancel_session_turn` resolves the pending
  approval as denied and the step is saved normally. **To verify:** that the
  Stop button is shown in this state.

**Fix:** include the pending approval (`tool_id`, `tool_name`, `args`,
`turn_id`, `subturn_id`) in the `session_state` payload, read from
`_state._pending_approvals` under its lock. The frontend opens the dialog from
it, deduplicating against a replayed `approval_request` with the same IDs.

### 2. In-progress step invisible after 1 hour (UI recovery, display only)

Reloading more than an hour into a long-running step hides that step's
`tool_call`/`tool_result` cards until the step finishes and is saved. No data
is lost.

**Fix:** either include the in-progress exchange in `session_state`, or
persist results incrementally (see 3), which also fixes this.

### 3. Stop while a tool is running drops executed side effects (history accuracy)

At an approval, Stop is careful: the pending call and all later queued calls
get the standard denial and the step is saved. But while a tool is *running*,
`cancel_session_turn` calls `task.cancel()`; `agent_loop` re-raises
`CancelledError` and the whole in-progress step is discarded — including
tools in that step that already finished and had real effects (files written,
shell commands run). History only gets `[Action Cancelled by User]`, so later
turns don't know those actions happened. A crash mid-step behaves the same.

This matters more with heartbeats, because the runner *itself* sends cancels
(see 5).

**Fix options:**
- Persist the in-progress exchange after each finished tool call (append the
  exchange to the subturn at step start, fill results in place, save after
  each result — `exchange_hash` already supports re-emitting a mutated
  exchange). On cancel, fill remaining calls with an interrupted/cancelled
  result, as `repair_incomplete_turn` does after a crash.
- Or route running-tool cancellation through `cancel_event` (cooperative, like
  the approval path) instead of `task.cancel()`, so `_execute_tools` returns
  the partial exchange with cancelled results for the unfinished calls.

### 4. No durable record of who approved what (audit)

An approved call looks identical to one that never needed approval. Heartbeat
forced decisions only go to the server log and Debug Panel (not durable).
With `force-approve` available, an audit trail becomes more important.

**Fix:** add an optional `approval` field to `ToolCallRecord`, e.g.
`{"decision": "approved"|"denied", "by": "human"|"heartbeat-policy"|"not-required", "policy": "...", "redirect_message": ...}`.
It is additive with a default, so no schema bump (same pattern as
`Subturn.origin`). Show it on the tool-call card.

## Heartbeat ↔ Live-User Interop

The runner (`src/ui_connector/heartbeat_runner.py`) launches with
`new_user_message(..., "new-task", background=True, origin="heartbeat")`; if
the session is busy it calls `cancel_session_turn` and retries every 60 s, up
to 3 cancels.

### 5. A heartbeat pre-empts a human's active turn

> **DONE (2026-09-26).** The turn reservation now records its owner
> (`state.reserved_turn_origin`). A due heartbeat never cancels a user-owned
> turn: it logs "Heartbeat skipped … has a running user turn" and returns
> False, so the daemon leaves the last run unrecorded and reconsiders the
> session at its next cycle (every 5 min). Only a heartbeat-owned turn (a stuck
> earlier heartbeat) goes through cancel-and-retry; if a user takes over during
> the retries, the runner stops without cancelling. Options below kept for
> history.

A human mid-turn — possibly looking at an approval dialog — gets their turn
cancelled by a due heartbeat. The pending approval is resolved as denied, and
the turn is closed with `[Action Cancelled by User]`, which is misleading.

Options to decide on:
- Only cancel turns whose current subturn has `origin == "heartbeat"` (a
  stuck previous heartbeat). For a human turn, skip or postpone the heartbeat
  and log it.
- Or keep pre-emption but use a distinct marker, e.g.
  `[Action Cancelled by Heartbeat]`, so the history and UI are truthful.
  (Requires passing a cancel reason through `cancel_session_turn` to the agent
  loop's `finally`.)
- Consider not firing at all while a browser is connected to the session
  (`_sid_to_session_id` has the session) and a turn is active.

### 6. The UI does not know a turn was heartbeat-started

> **DONE (2026-09-26).** `turn_start` carries `origin`; the UI stores it per
> subturn and every turn banner shows a Human / Heartbeat owner pill (owner =
> latest subturn's origin). Verified in code that backend-started turns lock
> the input: `onTurnStart` calls `setBusy(true)`.

`Subturn.origin` is persisted and serialized in `session_state`
(`subturn_to_dict`) but the live `turn_start` socket event doesn't carry it,
and nothing in the UI renders it.

**Fix:** add `origin` to the `turn_start` payload and show a heartbeat badge
on the user bubble (reuse the red `FaHeartbeat` icon). **To verify:** the
UI's local `busy`/input state correctly locks when a turn is started by the
backend (heartbeat), not by this browser's Send — and unlocks at the end.

### 7. A human message during a heartbeat turn is rejected

A human sending a message while a heartbeat turn runs gets "A turn is already
in progress". That is correct for safety, but the UI could say *why* (a
heartbeat is running) and offer Stop. Relates to 6.

### 8. Orphan reporting has no UI surface

"Session appears orphaned; restart recommended" only reaches the server log
(desktop Health tab). Consider also emitting a `backend_log` and/or a
persisted `error` event to the session so a user opening it sees the problem.

## Suggested Order

1. **Gap 1** (pending approval in `session_state`) — small, high value, needed
   for overnight `wait-for-human` heartbeats.
2. **Interop 5** (don't pre-empt human turns, or at least a truthful marker) —
   a policy decision first, then a small change.
3. **Gap 3** (incremental exchange persistence / cooperative cancel) — the
   real history-accuracy fix; touches the core turn loop, so do it on its own
   with focused tests.
4. **Items 6 and 7** (UI awareness of heartbeat turns).
5. **Gap 4** (approval audit field) and **item 8** (orphan surfaced in the UI).

## Test Ideas

- `session_state` includes a pending approval after Redis stream deletion;
  approving it resolves the original waiter (extend `tests/test_turn_hardening.py`).
- A running (non-approval) tool that finishes before Stop is still in the
  saved history after cancel; unfinished calls get a cancelled result and
  pairing stays valid.
- The heartbeat runner does not cancel a turn whose subturn origin is `user`
  (if that policy is chosen).
- `turn_start` carries `origin`; replaying `session_state` and a live event
  give the same badge.
