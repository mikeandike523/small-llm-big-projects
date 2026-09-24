# Hardening for Unexpected Message Start Events

## Status and Scope

This is a defensive hardening plan for enforcing **at most one active agent
turn per session**. It is not the explanation for ordinary batched tool calls:
one LLM response may legitimately contain several tool calls, all owned by one
agent loop. Batched tool-call rejection policy is a separate concern and should
be implemented separately.

The current browser UI prevents most duplicate submissions with local `busy`
state. That makes the system behave correctly during normal single-tab use,
but the backend itself does not atomically enforce the one-turn-per-session
invariant. Correctness should not depend on cooperative UI state.

## Current Flow

`handle_user_message` and `handle_force_continuation` in
`src/ui_connector/socket_handler_components/socket_events_turn.py` currently
use `_state._cancel_tasks` as their active-turn check:

```python
if session_id in _state._cancel_tasks:
    emit("error", {"message": "A turn is already in progress..."})
    return
```

The task is not inserted into `_cancel_tasks` until later, inside the new
asyncio event loop's `_run` coroutine. Before registration, the handler may:

- load the session and model configuration;
- run the continuation-classification LLM request;
- create or mutate the turn and subturn;
- emit `turn_start` and other session events; and
- create and install an event loop.

Flask-SocketIO runs in threaded mode, so two handlers for the same session can
both pass the check before either one registers its task. The check and the
reservation are separate operations with no lock around them.

`_session_active_turns` does not close this gap. It is populated only near
`loop.run_until_complete`, is not consulted by the turn-start handlers, and a
plain set membership check followed by `add` would still not be an atomic
reservation without synchronization.

## Race Sequence

The failure requires two independent message-start events, not multiple tool
calls in one model response:

```text
Handler A                              Handler B
---------                              ---------
check _cancel_tasks: absent
                                       check _cancel_tasks: absent
load session A                         load session B
classify/create turn A                 classify/create turn B
register cancel task A
                                       register cancel task B (overwrites A)
run agent loop A                       run agent loop B
```

Likely triggers include:

- a very fast double submission before React commits `busy=true`;
- two tabs or windows connected to the same durable session;
- chat and terminal-panel submissions racing;
- reconnect/retry or duplicate-delivery behavior;
- `force_continuation` racing with `user_message`; and
- future automated or external-channel message producers.

This is expected to be rare today because the UI suppresses normal duplicate
submissions and most turn setup reaches task registration quickly. The window
can be much larger when automatic continuation classification makes an LLM
request before the task is registered.

## Consequences

Once two loops exist for one session, multiple process-local structures assume
an exclusivity guarantee that no longer holds:

- `_cancel_tasks[session_id]` can reference only one of the two tasks.
- `_cancel_loops[session_id]` can reference only one event loop.
- `_pending_approvals[session_id]` can hold only one approval request.
- both loops can load, mutate, and save different in-memory copies of the same
  session;
- events from both loops interleave in the same Socket.IO room and Redis
  stream; and
- cleanup by one loop can remove state still owned by the other loop.

The approval failure is especially severe. `_request_approval` stores one
entry per session. A second loop can overwrite the first loop's entry, leaving
the first loop waiting on a `threading.Event` that is no longer reachable from
the pending-approval map. An approval response may then wake the wrong loop.

The Redis stream is not the source of the race. It gives the concurrently
submitted events a concrete order and therefore records the symptom.

## Related Approval-Correlation Weakness

`handle_approval_response` receives a tool-call ID but currently resolves the
pending entry for the session without checking that
`data["id"] == pending["tool_id"]`. A stale, duplicated, delayed, or
multi-tab response can therefore resolve a later approval request.

This can fail without two agent loops, although concurrent loops make it more
likely. Approval responses should be treated as correlated responses, not as
an instruction to resolve whichever approval happens to be current.

## Required Invariants

The hardened design should enforce these invariants in backend code:

1. A session has at most one admitted message-start operation at a time,
   including preprocessing and continuation classification.
2. The reservation is acquired atomically before session/turn mutation or any
   LLM request associated with the new turn.
3. Every successful reservation is released exactly once on every exit path.
4. Cancellation handles belong to the currently reserved turn but are not
   themselves the reservation mechanism.
5. An approval response resolves only the exact pending session, turn, and
   tool call it names.
6. An approval waiter removes only the pending entry it created.
7. A second pending approval for the same reserved session is rejected and
   logged as an invariant violation rather than silently overwriting state.

## Proposed Fix

### 1. Add an atomic per-session turn reservation

Create a small state helper rather than manipulating a shared set directly.
Use one process-local lock to protect the reservation set:

```python
_turn_reservations: set[str] = set()
_turn_reservations_lock = threading.Lock()


def try_reserve_turn(session_id: str) -> bool:
    with _turn_reservations_lock:
        if session_id in _turn_reservations:
            return False
        _turn_reservations.add(session_id)
        return True


def release_turn(session_id: str) -> None:
    with _turn_reservations_lock:
        _turn_reservations.discard(session_id)
```

The exact names and module can change, but acquisition must remain one atomic
check-and-add operation.

### 2. Reserve before preprocessing

Both `handle_user_message` and `handle_force_continuation` should reserve the
session immediately after resolving and validating `session_id`, before:

- loading or mutating the session;
- calling the continuation classifier;
- emitting `turn_start`; or
- installing cancellation/event-loop state.

If reservation fails, emit the existing “turn already in progress” error and
return without changing session state.

### 3. Release from an outer `finally`

Wrap the entire admitted operation—not merely `run_until_complete`—in a
`try/finally` that releases the reservation. This must cover early failures in
configuration loading, continuation classification, turn construction, event
loop creation, cancellation, and agent execution.

Avoid separate implementations whose cleanup behavior can drift between
`user_message` and `force_continuation`; extract a narrow reservation helper or
shared context manager if that makes exact cleanup easier to review.

### 4. Separate reservation state from cancellation state

Continue using `_cancel_tasks` and `_cancel_loops` to locate and cancel the
running asyncio task. Do not use their presence as the authoritative active
turn check.

This separation matters because a turn is already active during synchronous
preprocessing, before an asyncio task exists, and remains reserved during
cleanup after the task handle may have been removed.

`_session_active_turns` should either become a read-only/public status view of
the same reservation source or be removed to avoid two competing definitions
of “active.” HTTP endpoints and resume-session payloads should consult the
authoritative reservation state.

### 5. Correlate approval responses

Before resolving a pending approval, validate at least:

```text
session_id matches the map key
tool_id matches pending["tool_id"]
turn_id matches when supplied by the client
pending decision is still unresolved
```

For a mismatch, do not modify or signal the pending entry. Log a structured
warning containing the expected and received identifiers. The frontend may be
sent a stale-response error, but it must not cause the current approval to
resolve.

Including `turn_id` in the frontend's `approval_response` payload would make
the correlation boundary stronger and easier to diagnose.

### 6. Make pending-approval ownership identity-safe

`_request_approval` should retain the exact entry object it installs. When the
wait ends, remove the map entry only if the current value is that same object.
Do not blindly `pop(session_id)`, because that could remove a newer request.

Installing an approval when one is already pending for the same session should
raise or return a controlled internal error. It should never overwrite the
existing waiter.

### 7. Add diagnostic context

Log reservation acquire/reject/release and approval-correlation failures with:

- `session_id`;
- `turn_id`;
- `subturn_id` where available;
- `tool_id` for approvals; and
- the source event (`user_message` or `force_continuation`).

These logs should be diagnostic rather than normal UI chatter. They will make
future reports distinguish duplicate message starts from one response holding
multiple tool calls.

## Test Plan

### Atomic admission tests

- Start two `user_message` handlers for the same session behind a barrier so
  both attempt admission concurrently; assert exactly one acquires the
  reservation.
- Race `user_message` against `force_continuation`; assert exactly one starts.
- Verify different session IDs can reserve and run concurrently.
- Verify rejection performs no session mutation and emits no `turn_start`.

### Cleanup tests

- Release reservation after normal completion.
- Release after missing/invalid model configuration.
- Release after continuation-classifier failure.
- Release after cancellation and an exception from the agent loop.
- Confirm a new message can start after every cleanup case.

### Approval ownership tests

- A response with the correct tool ID resolves the waiter.
- A response with a stale or incorrect tool ID does not resolve it.
- A duplicate response after resolution does not affect a later approval.
- A second approval registration cannot overwrite the first.
- A waiter cannot remove a newer pending entry during cleanup.

### Integration event-order test

Drive a session through a model response that requires approval and attempt a
second message start while it waits. Assert that:

- the second start is rejected;
- only one agent loop emits events;
- the original approval still resolves the original tool; and
- the session history remains structurally valid.

## Acceptance Criteria

- Backend correctness no longer depends on the React `busy` flag.
- Exactly one of any concurrent same-session message-start events is admitted.
- Concurrent turns for different sessions remain supported.
- No pending approval can be overwritten or resolved by a mismatched tool ID.
- Cancellation and session-active reporting refer to the same admitted turn.
- All reservation and approval state is cleaned up after success, error, or
  cancellation.
- Existing single-tab behavior and event ordering remain unchanged.

## Non-Goals

- Do not change the fact that one LLM exchange may return multiple tool calls.
- Do not define batched tool-call denial or flush behavior here.
- Do not serialize different sessions globally.
- Do not move turn coordination into Redis unless the server is intentionally
  changed to a multi-process/multi-instance deployment model. The proposed
  process-local lock is appropriate for the current single backend process.

## Recommended Implementation Boundary

Implement this hardening in its own commit after the batched tool-call
rejection policy. Keeping the two changes separate makes their semantics and
tests clear:

- batched rejection governs multiple tool calls inside one valid agent loop;
- message-start hardening guarantees there is only one valid agent loop for a
  session in the first place.
