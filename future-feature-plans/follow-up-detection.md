# Follow-Up Detection & Continuation System

## Problem

When a user sends a follow-up message after a complex task, the current system creates
a new turn from scratch. The previous turn's full exchange history, live todo list state,
and tool call context are replaced by a condensed summary. This condensation loses enough
detail that follow-ups on complex tasks frequently fail.

## Goal

Recognize follow-up messages at the turn boundary and continue the existing turn instead
of starting a new one -- keeping the full exchange history, live todo state, and inherited
skill selection in context.

---

## Data Model: Turn / Subturn

The current `Turn` has a single `user_text` + a single `exchanges` list (one response arc).
Continuation breaks the 1:1 ratio. Introduce `Subturn`.

### New structure (session_model.py)

```python
@dataclass
class Subturn:
    id: str
    user_text: str
    user_text_with_context: str
    exchanges: list[LLMExchange]
    is_continuation: bool = False   # False for the first subturn, True for follow-ups

@dataclass
class Turn:
    id: str
    subturns: list[Subturn]         # replaces flat user_text + exchanges
    todo_snapshot: list
    task_title: str | None
    condensed_user: str
    condensed_assistant: str
    completed: bool
    was_cancelled: bool
    # was_impossible and impossible_reason are removed (see Tool Removal section)
```

`Turn.to_messages()` iterates subturns in order, producing:
```
[user: subturn1.user_text, ...subturn1.exchanges...,
 user: subturn2.user_text, ...subturn2.exchanges..., ...]
```

Each `LLMExchange` is unchanged. `user_continuation` continues to serve its existing
role (unclosed-todo reprompt, final-summary reprompt) -- it is not related to subturns.

The `Turn.finalize()` method uses the last subturn's final exchange content as
`final_content`. Condensed summary is built from the whole turn as before.

---

## New Watchdog: Continuation Detector

### When it runs

Before `handle_user_message` creates a new `Turn`, if there is at least one completed
turn in the session, run a YES/NO LLM call to decide whether the new message is a
follow-up.

### Token budget

Uses the same `watchdog_max_tokens` setting as the final-answer watchdog.

### Input

- Previous turn's `condensed_assistant` (last final response)
- Current todo list state: open item count and text if any items exist
- The new user message

### Prompt shape

```
System: You are deciding whether a new user message is a follow-up or continuation
of the previous task/response, or an independent new request.
Reply with exactly one word: YES or NO.
YES = the message continues, extends, redirects, or questions the previous response.
NO  = the message is an independent new request unrelated to the previous task.
When in doubt, reply NO.

User:
Previous assistant response:
{condensed_assistant}

Open todo items: {N}  (if any)
{open item text}

New user message:
{user_text}
```

The watchdog leans conservative: ambiguous cases return NO (new turn). This prevents
false positives that would pollute a large context window with irrelevant prior history.

### On YES (continuation)

1. Do not push the current turn to `completed_turns` yet -- keep it as the active turn.
   If the turn was already pushed (edge case: user waited, reconnected), pull it back.
2. Create a new `Subturn` with `is_continuation=True` and the new `user_text`.
3. Append the subturn to `turn.subturns`.
4. Inherit the previous subturn's dynamically selected skills -- skip re-running the
   skill selector (or re-run it with the full new context if the message suggests a
   topic shift).
5. Reset per-subturn agentic loop state:
   - `had_tool_calls = False`
   - `had_todo_items = False`
   - `final_summary_reprompt_sent = False`
   - `pending_final_candidate = None`
6. The final-answer watchdog scopes its evaluation to the current subturn's exchanges
   only (not the whole turn history).

### On NO

Normal new turn creation, exactly as today.

### Force YES: Follow-Up Button

The UI provides a "Follow Up" button (see UI section) that bypasses the continuation
watchdog entirely and forces `is_continuation=True`. Useful when the user knows they
are following up but the message text would not be recognized as such.

---

## Expanded Final-Answer Watchdog

The existing `_is_sufficient_final_answer()` watchdog (YES/NO: "is this a complete
response?") expands to detect three valid turn-ending response types, all returning YES:

1. **Completion** -- a final answer or summary of completed work.
2. **Question** -- the agent is expressing a need for clarification or explicit
   permission before it can proceed (replaces `ask_human`).
3. **Impossibility** -- the agent is reporting that the task cannot be completed
   with available tools/knowledge (replaces `report_impossible`).

Updated prompt fragment:

```
Reply YES if the latest reply is any of the following:
  - A direct final answer or summary of completed work.
  - A question or request for clarification directed at the user.
  - A statement that the task cannot be completed, with a clear explanation.

Reply NO if the reply is only a partial status update, reasoning fragment,
or interim step that does not resolve the turn.
```

### Follow-up after impossibility = implicit redirect

If the agent writes "I cannot complete X because Y" (watchdog YES, turn ends) and
the user follows up with "Try Z instead," the continuation detector fires YES. The
agent receives its own impossibility explanation and the user's redirect in full context
and proceeds. No explicit redirect dialog or socket event is needed.

---

## Tool Removals

Both tools are removed in the same implementation phase, after the continuation system
is stable.

### ask_human (removed)

**Current**: agent calls `ask_human(question)` mid-task, UI shows inline question widget,
user answers, loop resumes.

**Replacement**: agent expresses its question in its final answer text. Watchdog detects
this as a valid turn end (type: question). User follows up; continuation detector fires.
The agent's question and the user's answer are both in context when the loop resumes.

**Cleanup**:
- Delete `src/tools/ask_human.py`
- Remove `ask_human_fn` from `special_resources` in `_execute_tools`
- Remove `_request_human_input()`, `_pending_human_inputs`, `handle_ask_human_response()`
- Remove `ask_human_request` / `ask_human_resolved` socket events
- Remove `AskHumanItem`, `askHumanItems` from frontend Turn type and TurnBubble rendering
- Remove `ask_human_request` / `ask_human_resolved` socket listeners in Chat.tsx

**System prompt addition**:
> If you need clarification, a decision, or explicit permission before you can proceed,
> state your question or concern clearly as your final response and stop. Do not use
> tools for this. The user will follow up with an answer.

### report_impossible (removed)

**Current**: agent calls `report_impossible(reason)`, a redirect dialog appears, user
either confirms impossible or types a redirect instruction.

**Replacement**: agent writes "I cannot complete this because X" as its final answer.
Watchdog detects this as a valid turn end (type: impossibility). If the user wants to
redirect, they type a follow-up; continuation detector fires YES.

**Cleanup**:
- Delete `src/tools/report_impossible.py`
- Remove `_report_impossible` handling in `_execute_tools`
- Remove `_request_impossible_redirect()`, redirect dialog socket events
- Remove `was_impossible`, `impossible_reason` fields from `Turn` (or leave as vestigial
  no-ops if serialization compatibility is needed short-term)
- Remove `ImpossibleRedirectBubble`, `impossibleRedirectItem`, `impossibleBubble`,
  `report_impossible_request` / `report_impossible` socket listeners in Chat.tsx

---

## UI Changes

### Multi-segment turn bubble

A single turn bubble shows alternating segments within it:

```
[User message 1]          <- grey bubble
[AI response 1]           <- blue assistant bubble (existing style)
[User message 2]          <- grey bubble (follow-up)
[AI response 2]           <- blue assistant bubble
...
```

Tool calls, todo list, and the right column (reasoning, IRAT thinking) are scoped to
the currently active or most-recently-completed subturn. Earlier subturns' tool calls
are collapsed or shown in a lighter style.

### Follow-Up button

In the right column of a completed turn bubble (same area as Stop / Stop & Redirect),
add a **"Follow Up"** button. Behavior:

1. Clicking it opens a text-input widget (same visual style as the Stop & Redirect widget).
2. Submitting the text emits a `force_continuation` socket event with the message.
3. The backend skips the continuation watchdog and creates a new subturn unconditionally.
4. The turn bubble expands in-place to show the new subturn.

The button only appears on the most recently completed turn (not on historical turns
that are already condensed in a subsequent completed turn's payload).

### Turn bubble title / task title

With multiple subturns, the task title badge (if present) describes the whole arc, not
just the first subturn. No change needed to title generation logic -- it still fires
on the first subturn's content and stays for the lifetime of the turn bubble.

---

## Agentic Loop Changes (socket_handlers.py)

### handle_user_message

```
if session.completed_turns:
    is_continuation = await _is_continuation(streaming_llm, session, user_text, watchdog_max_tokens)
else:
    is_continuation = False

if is_continuation:
    turn = session.completed_turns.pop()   # re-open last turn
    subturn = Subturn(id=new_uuid(), user_text=..., is_continuation=True)
    turn.subturns.append(subturn)
    turn.completed = False
    session.current_turn = turn
else:
    turn = Turn(id=..., subturns=[Subturn(..., is_continuation=False)], ...)
    session.current_turn = turn
```

### _async_agent_loop

Per-subturn state variables (`had_tool_calls`, `pending_final_candidate`, etc.) are
reset at the start of each subturn. The loop otherwise works identically to today.

`_build_llm_payload` on a continued turn uses the full `turn.to_messages()` output
(all subturns), not condensed history. This is the key context-preservation benefit.

### force_continuation socket event (new)

```python
@socketio.on("force_continuation")
def handle_force_continuation(data):
    # same as handle_user_message but skips continuation watchdog, forces is_continuation=True
```

---

## Context Window Concern

Continued turns are never condensed mid-turn, so a long task with many follow-ups
can accumulate a large context. Mitigation (can be deferred):

- If turn exchange count exceeds a threshold, condense the earliest subturns in place
  (their full exchanges replaced with condensed_user/condensed_assistant text).
- This is analogous to the existing inter-turn condensation but applied within a turn.

---

## Implementation Phases

### Phase 1 -- Core continuation system (largest scope, do first)
- `Subturn` dataclass in `session_model.py`
- `Turn.to_messages()` updated to iterate subturns
- `_is_continuation()` watchdog function
- `handle_user_message` continuation detection logic
- `_async_agent_loop` per-subturn state reset
- `_build_llm_payload` uses full turn history on continuation
- Final-answer watchdog scoped to current subturn; prompt updated for question/impossibility
- UI: multi-segment turn bubble rendering
- Serialization: `Subturn` added to `turn_to_dict` / `turn_from_dict`

### Phase 2 -- Follow-up button
- UI button + text widget in right column of completed turn bubble
- `force_continuation` socket event (backend + frontend)

### Phase 3 -- Tool removal (after Phase 1 is stable)
- Remove `ask_human.py` and all related backend/frontend code
- Remove `report_impossible.py` and all related backend/frontend code
- Update system prompt
- Update final-answer watchdog prompt
- Remove `was_impossible` / `impossible_reason` from Turn (or leave vestigial)

---

## Open Questions (resolve before Phase 1)

1. **Continuation watchdog conservatism**: Confirmed lean-NO on ambiguity.

2. **Skill re-selection on continuation**: Inherit previous skills unchanged, or re-run
   the skill selector with the new message in context? Recommendation: inherit by default;
   re-run only if the follow-up message clearly shifts domain (hard to detect cheaply --
   probably just always inherit for now).

3. **When to show the Follow-Up button**: Only on the most recently completed turn, or
   on any completed turn? Recommendation: most recent only, since older turns are already
   condensed in subsequent turns' payloads and re-opening them would drop important context.

4. **Serialization schema version**: Adding `Subturn` is a breaking change to the Turn
   serialization. Bump `CURRENT_SCHEMA_VERSION` and add a migration in `session_from_dict`
   that wraps legacy `user_text` + `exchanges` into a single `Subturn`.
