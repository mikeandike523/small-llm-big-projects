# Architecture Report: small-llm-big-projects UI-to-Backend System

**Date:** March 2, 2026
**Scope:** Full stack — Flask/Socket.IO backend, Redis data layer, agentic loop, React frontend

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Topology](#2-system-topology)
3. [Redis Data Architecture](#3-redis-data-architecture)
   - 3.1 [Session Blob](#31-session-blob)
   - 3.2 [Memory Hash](#32-memory-hash)
   - 3.3 [Events Stream](#33-events-stream)
   - 3.4 [Key Naming and TTL Strategy](#34-key-naming-and-ttl-strategy)
4. [Session Model: The Turn/Exchange Hierarchy](#4-session-model-the-turnexchange-hierarchy)
   - 4.1 [Data Classes](#41-data-classes)
   - 4.2 [Turn Lifecycle](#42-turn-lifecycle)
   - 4.3 [Message Reconstruction](#43-message-reconstruction)
   - 4.4 [Condensation for Future Turns](#44-condensation-for-future-turns)
5. [Socket.IO: Rooms and Connection Multiplexing](#5-socketio-rooms-and-connection-multiplexing)
   - 5.1 [Why Rooms, Not SIDs](#51-why-rooms-not-sids)
   - 5.2 [The SID-to-Session Mapping](#52-the-sid-to-session-mapping)
   - 5.3 [Threading Model](#53-threading-model)
6. [Connection Lifecycle](#6-connection-lifecycle)
   - 6.1 [Initial Connection](#61-initial-connection)
   - 6.2 [The resume_session Handshake](#62-the-resume_session-handshake)
   - 6.3 [Disconnect and Reconnect](#63-disconnect-and-reconnect)
7. [The Agentic Loop](#7-the-agentic-loop)
   - 7.1 [Overall Structure](#71-overall-structure)
   - 7.2 [Tool Execution](#72-tool-execution)
   - 7.3 [Unclosed Todo Reprompting](#73-unclosed-todo-reprompting)
   - 7.4 [Final Reprompt](#74-final-reprompt)
   - 7.5 [Context-Strip Retry](#75-context-strip-retry)
   - 7.6 [Approval Gating](#76-approval-gating)
8. [The Event System: _emit_and_log and Redis Streams](#8-the-event-system-_emit_and_log-and-redis-streams)
   - 8.1 [_emit_and_log](#81-_emit_and_log)
   - 8.2 [REPLAY_EXCLUDED_EVENTS](#82-replay_excluded_events)
   - 8.3 [replay_content_snapshot](#83-replay_content_snapshot)
9. [Redis-Backed Dictionary (RedisDict)](#9-redis-backed-dictionary-redisdict)
   - 9.1 [Design and Interface Compatibility](#91-design-and-interface-compatibility)
   - 9.2 [The on_change Callback](#92-the-on_change-callback)
   - 9.3 [Limitations and Safety Notes](#93-limitations-and-safety-notes)
10. [EmittingKVManager: Reactive Project Memory](#10-emittingkvmanager-reactive-project-memory)
11. [Frontend Architecture](#11-frontend-architecture)
    - 11.1 [Session Identity and Socket Lifecycle](#111-session-identity-and-socket-lifecycle)
    - 11.2 [Thread State Model](#112-thread-state-model)
    - 11.3 [The Replay Processor](#113-the-replay-processor)
    - 11.4 [Live Event Handlers](#114-live-event-handlers)
12. [Event Replay and Reconnect Resilience](#12-event-replay-and-reconnect-resilience)
    - 12.1 [The lastEventId Cursor](#121-the-lasteventid-cursor)
    - 12.2 [Animated vs. Fast Replay](#122-animated-vs-fast-replay)
    - 12.3 [In-Progress Turn Restoration](#123-in-progress-turn-restoration)
13. [Session Storage and Scroll Persistence](#13-session-storage-and-scroll-persistence)
14. [Loading Modal](#14-loading-modal)
15. [Innovations and Design Highlights](#15-innovations-and-design-highlights)

---

## 1. Introduction

This document describes the complete architecture of the `small-llm-big-projects` agent UI system — from the moment a user types a message in the browser, to the LLM receiving it, to tool calls being executed on the server, to the results streaming back to the screen — including what happens when the browser tab is closed and reopened mid-run.

The system is built around a few central design goals that distinguish it from conventional chat interfaces:

- **Stable sessions.** The session is tied to a UUID the browser generates and stores in `sessionStorage`, not to a transient WebSocket connection. This means disconnecting does not destroy the session.
- **Structured turn data.** Rather than storing a flat list of raw LLM messages, the system uses a hierarchical data model: `Session → Turn → LLMExchange → ToolCallRecord`. This structure supports efficient context construction, replay, and UI rendering independently.
- **Live event replay.** Every significant event emitted during a turn is written to a Redis Stream. On reconnect, the client sends a cursor and receives back anything it missed, enabling seamless resume of in-progress agent runs.
- **Reactive memory UI.** Session and project memory are backed by live data structures that automatically push UI updates when modified by any tool call, without any polling.

**Audience note:** This report assumes familiarity with web development concepts (HTTP, WebSockets, JSON, React) and basic knowledge of how databases store data. No prior knowledge of Redis, Socket.IO internals, or LLM APIs is assumed — those are explained where they appear.

---

## 2. System Topology

Figure 2.1 shows the full component layout.

```
Figure 2.1 — System Component Topology

  ┌─────────────────────────────────────────────────────────────┐
  │  Browser Tab (React + Vite, port 5173)                      │
  │                                                             │
  │  sessionStorage                                             │
  │  ├── session_id  (stable UUID, survives page refresh)       │
  │  ├── lastEventId (Redis Streams cursor)                     │
  │  └── scroll:*   (per-container scroll positions)           │
  │                                                             │
  │  Chat.tsx  ←──── socket.io-client (WebSocket transport)    │
  └──────────────────────────┬──────────────────────────────────┘
                             │  ws:// (WebSocket)
                             │  ?sessionId=<uuid>
  ┌──────────────────────────▼──────────────────────────────────┐
  │  Flask + Flask-SocketIO (port 5000, async_mode="threading") │
  │                                                             │
  │  socket_handlers.py                                         │
  │  ├── handle_connect      → join_room(session_id)            │
  │  ├── handle_resume_session → session_state + event_replay   │
  │  ├── handle_disconnect   → clean SID map only               │
  │  ├── handle_user_message → agentic loop                     │
  │  └── handle_*            → query / info handlers            │
  │                                                             │
  │  _emit_and_log()  → Redis Streams + socketio.emit(room=)    │
  │                                                             │
  └──────────────────────────┬──────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
  ┌───────▼───────┐  ┌───────▼───────┐  ┌──────▼────────┐
  │  Redis        │  │  MySQL / DB   │  │  LLM API      │
  │               │  │               │  │  (OpenAI-      │
  │  session:*    │  │  tokens table │  │   compatible   │
  │  :memory      │  │  kv_store     │  │   endpoint)    │
  │  :events      │  │  project mem  │  │               │
  └───────────────┘  └───────────────┘  └───────────────┘
```

Three backend data stores serve different roles:

- **Redis** — ephemeral session data, session memory (key-value pairs the agent accumulates), and the event replay log. All Redis data has a 1-hour TTL.
- **MySQL** — persistent project memory (key-value store), LLM token credentials, and configuration parameters. This data survives server restarts.
- **LLM API** — a remote HTTP endpoint that the server calls to generate responses. The server uses Server-Sent Events (streaming) or a single fetch, depending on configuration.

---

## 3. Redis Data Architecture

Redis is used for three distinct purposes per session, each with its own key and data type. Understanding the distinction is important because they have different access patterns, serialization formats, and ownership semantics.

### 3.1 Session Blob

**Key:** `session:{session_id}`
**Redis type:** String (stores a JSON document)
**TTL:** 3600 seconds (refreshed on every save)

The session blob is the primary persistence unit. It stores the complete state of a session as a JSON document. It is written atomically via `SETEX` and read via `GET`. The schema (version 2) is:

```
Figure 3.1 — Session Blob JSON Schema

{
  "schema_version": 2,
  "session_id":     "uuid-string",
  "startup_done":   true | false,

  "completed_turns": [
    {
      "id":                    "uuid-string",
      "user_text":             "raw user input",
      "user_text_with_context": "user input + env context suffix",
      "exchanges": [
        {
          "assistant_content": "text from LLM",
          "reasoning":         "chain-of-thought (if any)",
          "is_final":          true | false,
          "user_continuation": "injected follow-up user message | null",
          "tool_calls": [
            {
              "id":          "call-uuid",
              "name":        "tool_name",
              "args":        { ... },
              "result":      "string output | null",
              "was_stubbed": false
            }
          ]
        }
      ],
      "todo_snapshot":       [ ... ],
      "was_impossible":      false,
      "impossible_reason":   null,
      "completed":           true,
      "condensed_user":      "brief user text for LLM context",
      "condensed_assistant": "brief assistant summary for LLM context"
    }
  ],

  "current_turn": { ... same Turn schema ... } | null,

  "session_data": {
    // arbitrary persistent tool state (e.g. change_pwd history)
    // EXCLUDES: memory, todo_list, _report_impossible, __pinned_project__
  }
}
```

**What is NOT saved in the blob:**

| Key | Where instead |
|-----|---------------|
| `memory` | Redis hash `session:{id}:memory` |
| `todo_list` | Ephemeral; snapshotted in `Turn.todo_snapshot` at turn end |
| `_report_impossible` | Ephemeral flag, always popped before save |
| `__pinned_project__` | Re-injected before each tool call from server config |

This separation is important. The `session_data` dict in the blob is meant for persistent cross-turn tool state that tools write freely — things like the current working directory, cached resource handles, or any state the tools themselves manage. Keeping ephemeral or separately-stored keys out of it avoids bloat and correctness bugs (e.g. the old bug where `_report_impossible` would persist to the next turn).

### 3.2 Memory Hash

**Key:** `session:{session_id}:memory`
**Redis type:** Hash (field → value, all strings)
**TTL:** 3600 seconds (refreshed on every session save)

The session memory is a key-value store that the agent can read and write freely via the `session_memory` tool family. It is stored in a Redis Hash rather than inside the session blob for two reasons:

1. **Atomicity.** Individual `HSET` and `HDEL` operations are atomic. The agent can write a single memory key without loading, modifying, and re-serializing the entire session blob.
2. **Reactivity.** The hash is wrapped in a `RedisDict` (see §9) with an `on_change` callback. Every `HSET`/`HDEL` automatically triggers a Socket.IO push to the UI, so the debug panel always shows live memory state.

### 3.3 Events Stream

**Key:** `session:{session_id}:events`
**Redis type:** Stream (append-only log with auto-generated IDs)
**TTL:** 3600 seconds (refreshed on every session save)

Redis Streams is a data structure purpose-built for append-only event logs with consumer-group support. This system uses it in its simplest form: as a sequential log that can be read with `XRANGE` from any point forward.

Every significant event that the backend emits during a turn (tool calls, tool results, turn start, message done, approval events, etc.) is appended to this stream by `_emit_and_log()`. Each entry has:

```
Figure 3.2 — Redis Stream Entry Structure

Stream ID:  "1740929012345-0"  (millisecond timestamp + sequence number)
Fields:
  type:  "tool_call"
  data:  '{"id":"call-1","name":"list_dir","args":{...},"turn_id":"uuid",...}'
```

The stream ID serves as a cursor — the client stores the ID of the last event it processed, and on reconnect sends it back. The server calls `XRANGE` with exclusive start `(last_id` to get only events the client hasn't seen.

**What is NOT logged to the stream:**

| Excluded event | Reason |
|----------------|--------|
| `token` | Very high volume (one per streamed token); content is reconstructed from `replay_content_snapshot` snapshots instead |
| `backend_log` | Informational only, not needed for state reconstruction |
| `session_memory_keys_update` | Derived state; re-emitted by `RedisDict.on_change` which fires on any memory read after reconnect |
| `session_memory_key_event` | Same |
| `project_memory_key_event` | Same |

### 3.4 Key Naming and TTL Strategy

```
Figure 3.3 — Redis Key Namespace

session:{uuid}           → Session blob (JSON, SETEX)
session:{uuid}:memory    → Session memory (Hash, EXPIRE only)
session:{uuid}:events    → Event log (Stream, EXPIRE only)
```

All three keys share the same UUID prefix, making it easy to identify and clean up a session's complete Redis footprint. The TTL is 3600 seconds (1 hour), which is refreshed on every `_save_session()` call. This means an actively-used session never expires; only abandoned sessions eventually disappear.

**Design justification:** A 1-hour TTL is short enough to prevent Redis from accumulating stale data indefinitely, but long enough to tolerate a user walking away from a long tool run for a coffee break and returning to resume. It is a deliberate choice that sessions are ephemeral in Redis — truly persistent memory is stored in MySQL via `project_memory`.

---

## 4. Session Model: The Turn/Exchange Hierarchy

The session model (defined in `src/utils/session_model.py`) is the structural backbone of the entire system. Understanding it is prerequisite to understanding both the agentic loop and the frontend render logic.

### 4.1 Data Classes

```
Figure 4.1 — Session Model Hierarchy

Session
├── session_id: str              (stable UUID from browser)
├── schema_version: int = 2
├── startup_done: bool
├── session_data: dict           (persistent tool state)
├── current_turn: Turn | None    (in-progress, null when idle)
└── completed_turns: list[Turn]

Turn
├── id: str                      (UUID, client-provided)
├── user_text: str               (raw input, no env context)
├── user_text_with_context: str  (input + OS/cwd env suffix)
├── exchanges: list[LLMExchange]
├── todo_snapshot: list          (todo state at turn completion)
├── was_impossible: bool
├── impossible_reason: str | None
├── completed: bool
├── condensed_user: str          (used in future turns' context)
└── condensed_assistant: str     (used in future turns' context)

LLMExchange
├── assistant_content: str       (text output of this LLM call)
├── reasoning: str               (chain-of-thought, if model supports it)
├── is_final: bool               (True = no tool calls, last exchange of turn)
├── user_continuation: str|None  (injected follow-up: unclosed todo / final summary)
└── tool_calls: list[ToolCallRecord]

ToolCallRecord
├── id: str
├── name: str
├── args: dict
├── result: str | None
└── was_stubbed: bool
```

### 4.2 Turn Lifecycle

A single user message ("turn") maps to one or more LLM calls, each producing an `LLMExchange`. The typical lifecycle:

```
Figure 4.2 — Turn Lifecycle State Transitions

  user sends message
        │
        ▼
  Turn created (id=clientTurnId, user_text=text)
  session.current_turn = turn
        │
        ▼ ─────────────────────────────────────────────────────────────┐
  LLM call → LLMExchange                                               │
        │                                                               │
        ├── has_tool_calls == True                                      │
        │       │                                                       │
        │       ▼                                                       │
        │   _execute_tools() → ToolCallRecord × N                      │
        │   exchange.is_final = False                                   │
        │   turn.exchanges.append(exchange)                             │
        │   _save_session()           ← checkpoint after each batch    │
        │       │                                                       │
        │       ├── impossible == True → emit report_impossible         │
        │       │                        emit message_done             │
        │       │                        turn_completed = True  ───────┤ break
        │       │                                                       │
        │       └── continue ──────────────────────────────────────────┘
        │
        └── has_tool_calls == False (final text response)
                │
                ├── unclosed todos exist → inject user_continuation
                │                          turn.exchanges.append()
                │                          continue ─────────────────────┘
                │
                ├── had_tool_calls and not final_reprompt_done
                │       │
                │       ├── all_closed and has_content → emit message_done
                │       │                                turn_completed = True  break
                │       │
                │       └── inject user_continuation (final summary request)
                │           continue ─────────────────────────────────────────┘
                │
                └── emit message_done, turn_completed = True  break

  Turn finalize:
    turn.completed = True
    turn.todo_snapshot = current todo_list
    turn.finalize() → condensed_user, condensed_assistant
    session.completed_turns.append(turn)
    session.current_turn = None
    _save_session()
```

### 4.3 Message Reconstruction

The method `Turn.to_messages()` rebuilds the full OpenAI-compatible message list from the `exchanges` list. This is what gets passed to the LLM at each call within a turn:

```
Figure 4.3 — Message Reconstruction from Exchanges

Given exchanges = [ex0(tool_calls), ex1(tool_calls), ex2(is_final)]:

to_messages() output:
  [
    { role: "user",      content: user_text_with_context },

    // ex0: interim with tools
    { role: "assistant", content: ex0.assistant_content,
                         tool_calls: [{ id, function: {name, arguments} }] },
    { role: "tool",      tool_call_id: tc.id, content: tc.result },
    ...
    { role: "user",      content: ex0.user_continuation },  // if set

    // ex1: interim with tools
    { role: "assistant", ... tool_calls: [...] },
    { role: "tool",      ... },
    { role: "user",      content: ex1.user_continuation },  // if set

    // ex2: final
    { role: "assistant", content: ex2.assistant_content }
  ]
```

The `user_continuation` field on `LLMExchange` is key — it allows the system to inject structured follow-up messages (e.g., "You still have 2 unclosed todo items") into the exact correct position in the message history, without mutating or re-processing the rest of the turn.

**Why this matters:** A naive implementation might concatenate these strings onto `user_text_with_context`, or append them as separate items to a flat list. Both approaches break the message ordering invariant that OpenAI-compatible APIs require (every `tool` message must immediately follow its corresponding `assistant` message with `tool_calls`). The `user_continuation` pattern solves this correctly at the data-model level.

### 4.4 Condensation for Future Turns

When a turn completes, `Turn.finalize()` computes two short strings — `condensed_user` and `condensed_assistant` — that represent the turn for the LLM context in all future turns. This is how the system avoids re-sending the full multi-exchange message history for previous turns.

```python
# Turn with tool calls — condensed assistant:
"Hi. To complete your request, I called 7 tools, completed 3 todo items,
and arrived at this answer/summary: <final_content>"

# Turn without tool calls — condensed is just the raw messages:
condensed_user = user_text
condensed_assistant = final_content
```

This is a deliberate compression: completed turns become a single `user`/`assistant` pair in the payload, regardless of how many exchanges they actually involved. The trade-off is that the exact tool call history is lost from the LLM's view of past turns — but retained fully in `Turn.exchanges` for the UI and for the current-turn context (where the full message list is used).

---

## 5. Socket.IO: Rooms and Connection Multiplexing

### 5.1 Why Rooms, Not SIDs

Socket.IO assigns each WebSocket connection a "SID" (session ID) — a per-connection identifier that changes every time the connection is established. The naive approach is to use the SID as the key for everything: session storage, event targets, pending state. This approach has a fatal flaw: disconnects and reconnects produce new SIDs, which breaks continuity of the session.

The correct approach is to use Socket.IO **rooms** — named channels that any number of connected clients can join. A client emits to a room, and all members of that room receive the event. In this system, each session has a room named after its stable `session_id` UUID.

```
Figure 5.1 — SID vs Room Routing

BEFORE (SID-based):
  Browser Tab ──────────── SID: "abc123" ──→ session:"abc123"
  (reconnects)              SID: "def456" ──→ session:"def456"  ← NEW, EMPTY
                             ↑ data lost

AFTER (Room-based):
  Browser Tab ──────────── SID: "abc123" ─┐
  (reconnects)              SID: "def456" ─┤→ room:"uuid-123" ──→ session:"uuid-123"
                                           ↑ same room, data intact
```

All `socketio.emit(...)` calls in `socket_handlers.py` use `room=session_id`, never the SID directly (except for immediate error responses in `handle_connect` before the room is joined). This means the session's event stream targets the room, and any future reconnects automatically receive events because they join the same room.

### 5.2 The SID-to-Session Mapping

The `_sid_to_session_id` dictionary in `socket_handlers.py` is a simple lookup table:

```python
_sid_to_session_id: dict[str, str] = {}
# Key:   SID (transient, per-connection)
# Value: session_id (stable, from browser sessionStorage)
```

- **On connect:** `_sid_to_session_id[sid] = session_id`
- **On disconnect:** `_sid_to_session_id.pop(sid, None)` — cleaned up, but the session data in Redis remains untouched.

This design means the server never confuses "the connection went away" with "the session is over". The session persists in Redis; only the routing entry is removed.

**Justification:** The session_id is the user's identity for this browser tab. Decoupling it from the transport-layer SID is the fundamental insight that makes reconnect resilience possible.

### 5.3 Threading Model

The server uses `async_mode="threading"` in Flask-SocketIO. This means:

- Each Socket.IO event handler runs in its own Python thread, pulled from a thread pool.
- The agentic loop (which can run for minutes, blocking on LLM responses and tool executions) runs in its own thread without blocking the event loop.
- Shared mutable state (`_sid_to_session_id`, `_pending_approvals`, `_log_counter`) uses threading primitives: `dict` operations are GIL-protected, `_log_counter` uses an explicit `threading.Lock()`.
- The approval gate uses `threading.Event()` — a standard synchronization primitive — to block the agentic loop thread while waiting for the user's browser response.

This is in contrast to an `async` (asyncio-based) architecture, which would require `await`-aware code throughout. The threading model is a deliberate choice for simplicity given that tool calls are I/O-bound (filesystem, HTTP, subprocess) and the GIL is released during I/O.

---

## 6. Connection Lifecycle

### 6.1 Initial Connection

```
Figure 6.1 — Initial Connection Sequence

  Browser                          Server                          Redis
     │                               │                               │
     │  WebSocket upgrade            │                               │
     │  GET /socket.io/?sessionId=X  │                               │
     ├──────────────────────────────►│                               │
     │                               │  _sid_to_session_id[sid] = X │
     │                               │  join_room(X)                │
     │                               │                               │
     │  emit("resume_session",       │                               │
     │       {lastEventId: "0-0"})   │                               │
     ├──────────────────────────────►│                               │
     │                               │  LOAD session:X ─────────────►│
     │                               │◄─────────────────────────────┤
     │                               │  GET events since "0-0" ─────►│
     │                               │◄─────────────────────────────┤
     │◄──────────────────────────────┤  emit("session_state", {...}) │
     │◄──────────────────────────────┤  emit("event_replay", {...})  │
     │                               │  (if events exist)            │
```

There is a deliberate subtlety in the sequence: the client sends `resume_session` immediately after connecting, and the server only emits the startup log *after* loading the session (in `handle_resume_session`, not in `handle_connect`). This ensures the client has registered all its socket event handlers before receiving any data.

**On the frontend:** The socket's `autoConnect: false` option means the socket does not attempt a connection until `socket.connect()` is called explicitly — which happens only *after* all `socket.on(...)` handlers are registered. This prevents a race condition where the `connect` event fires before the handler for `session_state` is installed.

### 6.2 The resume_session Handshake

`handle_resume_session` is the main reconnect protocol handler. It performs three steps:

1. **Load session from Redis.** If the schema version does not match `CURRENT_SCHEMA_VERSION`, it emits `session_state { schemaInvalid: true }` and returns — the frontend resets to a clean state.
2. **Emit `session_state`.** Sends the full list of `completed_turns` (serialized as Turn dicts) and the `current_turn` (if any) and the `startup_done` flag.
3. **Emit `event_replay`.** Queries `session:{id}:events` for all events after `lastEventId`. If there are any, emits them in a single batch.

This three-step sequence ensures the client can fully reconstruct the conversation state even after a hard refresh.

### 6.3 Disconnect and Reconnect

```
Figure 6.2 — Disconnect and Reconnect Behavior

  DURING DISCONNECT:
  handle_disconnect():
    - Pop _sid_to_session_id[sid]        ← routing cleanup only
    - Release pending approval gate      ← prevents agentic loop from
      (approved=False, event.set())         hanging forever
    - DO NOT touch Redis                 ← session fully intact

  AFTER RECONNECT (agentic loop still running):
    Browser sends resume_session
    Server loads session (current_turn is set)
    Server emits session_state with currentTurn
    Server emits event_replay with all events since lastEventId

    Frontend:
      - Restores completed turns
      - Creates in-progress turn with streaming=true
      - Processes replayed events in animated or fast-replay mode
      - Resumes showing live token events from the still-running loop
```

The approval release deserves special attention. If the agentic loop is blocked waiting for user approval (`_request_approval` is in `ev.wait(timeout=60)`) and the browser disconnects, `handle_disconnect` sets `approved=False` and fires the event. The agentic loop resumes immediately, treats the denial as user denial, and records a "user denied approval" result. The loop does not hang waiting for a client that is no longer connected. This is a correctness guarantee: a session can always make forward progress, or terminate cleanly, regardless of client connectivity.

---

## 7. The Agentic Loop

The agentic loop is the core of `handle_user_message`. It is a while-loop that calls the LLM, executes any tool calls, re-calls the LLM with updated context, and repeats until the LLM produces a response with no tool calls (a "final" response).

### 7.1 Overall Structure

```
Figure 7.1 — Agentic Loop Control Flow

  handle_user_message(data):
    session = _load_session(session_id)
    current_turn = Turn(id=clientTurnId, ...)
    session.current_turn = current_turn

    emit turn_start

    had_tool_calls = False
    final_reprompt_done = False

    WHILE True:
      ┌─────────────────────────────────────────┐
      │ IF had_tool_calls AND NOT final_reprompt │
      │   emit begin_interim_stream              │
      └─────────────────────────────────────────┘

      payload = _build_llm_payload(session, current_turn)
      result, content, reasoning = _run_llm_call_with_retry(payload)

      ┌──────────────────────────────────────────────────────────┐
      │ IF result.has_tool_calls:                                 │
      │   exchange = _execute_tools(result, ...)                 │
      │   turn.exchanges.append(exchange)                        │
      │   _save_session()                                        │
      │   IF impossible: emit report_impossible, message_done    │
      │                  BREAK                                   │
      │   ELSE: CONTINUE                                         │
      ├──────────────────────────────────────────────────────────┤
      │ ELSE (no tool calls):                                     │
      │   IF unclosed todos: inject user_continuation, CONTINUE  │
      │   IF had_tool_calls AND NOT final_reprompt:              │
      │       IF all_closed AND has_content: emit message_done   │
      │                                      BREAK               │
      │       ELSE: inject summary request, CONTINUE             │
      │   ELSE: emit message_done, BREAK                         │
      └──────────────────────────────────────────────────────────┘

    Finalize turn: condensed_user/assistant, todo_snapshot
    session.completed_turns.append(turn)
    session.current_turn = None
    _save_session()
```

### 7.2 Tool Execution

`_execute_tools()` iterates over `result.tool_calls`, executing each one:

1. If the tool needs approval (`check_needs_approval(name, args)`): call `_request_approval()`, which blocks the thread until the user approves, denies, or the 60-second timeout elapses.
2. Call `execute_tool(name, args, session_data, special_resources)`.
3. If the result exceeds `return_value_max_chars`: stub it. The full value is stored in session memory under a generated key, and the tool result is replaced with a pointer and preview. The LLM sees the abbreviated result; it can retrieve the full value by key if needed.
4. Build a `ToolCallRecord` and append it to the exchange.
5. Emit `tool_call` and `tool_result` events.

A critical correctness guarantee: `_execute_tools()` wraps the entire loop in a `try/finally` that always pops `_report_impossible` from `session_data`. This key is set by the `report_impossible` tool (or by an approval denial) and signals to the caller that the turn should be terminated as impossible. The `finally` ensures it never leaks into the next save.

### 7.3 Unclosed Todo Reprompting

The `todo_list` tool allows the LLM to maintain a hierarchical task list. If the LLM's final response (no tool calls) arrives but there are still open todo items, the system does not accept it as complete. Instead, it injects a `user_continuation` message into the current exchange:

```
"You still have 2 unclosed todo item(s). Please continue:
  1. write the unit tests
  2. update the README"
```

The loop then continues, giving the LLM another chance to complete the remaining items. This is a form of structured prompting: rather than relying on the LLM to self-check its own completeness, the system enforces it programmatically.

### 7.4 Final Reprompt

When the LLM has completed all tool calls (no more tool calls in its response) and all todo items are closed, the system checks whether the LLM's response is just an interim-stream assistant message (produced mid-run while tool calls were still happening). If so, it requests a final summary:

```
"All action items are complete. Please provide your final summary or answer
based on the steps you took, the tool results, and the previous context."
```

This reprompt produces the `LLMExchange` with `is_final=True` — the exchange whose `assistant_content` is shown in the main conversation bubble. The intermediate tool-running responses are visible in the debug/reasoning panel but not as the primary output.

**Why this matters for UX:** Without a final reprompt, the user would see the last tool-running stream (e.g., "Now I'll update the file...") as the final response, rather than a coherent summary. The reprompt guarantees the final response is always a well-formed wrap-up from the LLM's perspective.

### 7.5 Context-Strip Retry

If the LLM call fails due to a context-length error (HTTP 400/413/422 with relevant error keywords) or a network timeout, `_run_llm_call_with_retry` strips the payload using `strip_down_messages()` and retries once. The stripping removes or truncates tool results, assistant interim content, and other large items according to per-tool `LEAVE_OUT` policies (KEEP, PARAMS_ONLY, SHORT, OMIT). This allows long conversations to continue even when the full context would exceed the model's token limit.

### 7.6 Approval Gating

The approval gate blocks the agentic loop thread using `threading.Event.wait()`. The backend emits an `approval_request` event to the room, and the frontend renders approve/deny buttons. When the user clicks a button, the browser emits `approval_response`, which sets the event and unblocks the thread.

The 60-second timeout was added to handle the case where the browser disconnects while an approval is pending. Without the timeout, the thread would block indefinitely.

```
Figure 7.2 — Approval Gate Sequence

  Agentic Loop Thread          Frontend                    Backend Handler Thread
         │                        │                               │
         │  emit approval_request │                               │
         ├───────────────────────►│                               │
         │  ev.wait(timeout=60)   │  show Approve/Deny buttons    │
         │  (BLOCKED)             │                               │
         │                        │  user clicks Approve          │
         │                        ├──────────────────────────────►│
         │                        │  emit('approval_response', ..)│
         │                        │                               │  pending["approved"] = True
         │                        │                               │  pending["event"].set()
         │  ev.wait() returns     │                               │
         │◄───────────────────────────────────────────────────────┤
         │  approved = True       │                               │
         │  continue tool exec    │                               │
```

---

## 8. The Event System: _emit_and_log and Redis Streams

### 8.1 _emit_and_log

Every meaningful event emitted during a turn passes through `_emit_and_log()`:

```python
def _emit_and_log(session_id: str, event_type: str, data: dict) -> None:
    if event_type not in REPLAY_EXCLUDED_EVENTS:
        event_id = log_event(r, session_id, event_type, data)
        data = {**data, "event_id": event_id}   # ← inject stream ID
    socketio.emit(event_type, data, room=session_id)
```

The injected `event_id` is the Redis Stream auto-generated ID (a millisecond timestamp with a sequence suffix, e.g. `"1740929012345-0"`). The client stores this as `lastEventId` in `sessionStorage`. On the next connect, it sends this cursor and the server returns only events after that ID via `XRANGE`.

```
Figure 8.1 — Event Flow Through _emit_and_log

  Agentic Loop
       │
       ▼
  _emit_and_log(session_id, "tool_call", {id, name, args, turn_id})
       │
       ├── event_type NOT in REPLAY_EXCLUDED_EVENTS?
       │       YES:
       │       │   XADD session:{id}:events  {type, data: json}
       │       │         → returns stream_id = "1740929012345-0"
       │       │   data["event_id"] = stream_id
       │       │
       └── socketio.emit("tool_call", data, room=session_id)
               │
               └── delivered to all WebSocket connections in room
```

This architecture means every event is both live-delivered to the current connection *and* durably logged for future replay — in a single call. There is no risk of an event being emitted without being logged, or logged without being emitted.

### 8.2 REPLAY_EXCLUDED_EVENTS

The events excluded from the replay log are excluded for specific, deliberate reasons:

| Event | Reason for exclusion |
|-------|---------------------|
| `token` | One event per token, potentially thousands per turn. Content is recovered from `replay_content_snapshot` snapshots instead. |
| `backend_log` | Informational/diagnostic. Not needed to reconstruct UI state. |
| `session_memory_keys_update` | Derived from the memory hash; the hash persists separately and keys are re-queried on reconnect via the debug panel's refresh mechanism. |
| `session_memory_key_event` | Same — derived state. |
| `project_memory_key_event` | Same. |

All other events — `turn_start`, `tool_call`, `tool_result`, `begin_interim_stream`, `begin_final_summary`, `todo_list_update`, `approval_request`, `approval_resolved`, `approval_timeout`, `report_impossible`, `message_done`, `error`, `replay_content_snapshot` — are logged.

### 8.3 replay_content_snapshot

Since `token` events are excluded from the replay log, the system needs another way to recover the accumulated content of an in-progress LLM exchange during replay. This is solved by `replay_content_snapshot`:

```python
# Emitted every 50 tokens AND at the end of every LLM call:
_emit_and_log(session_id, "replay_content_snapshot", {
    "turn_id": turn_id,
    "exchange_idx": exchange_idx,   # which exchange (0-indexed)
    "assistant_content": acc["content"],
    "reasoning": acc_reasoning,
})
```

On the live path, the frontend ignores `replay_content_snapshot` (it already has the tokens). On the replay path, it applies the snapshot to set the full content of the specified exchange. The 50-token periodicity means the worst-case "missed content" per replay is 50 tokens — acceptable for a reconnect scenario.

**Innovation note:** The combination of "exclude individual tokens from the log but periodically snapshot accumulated content" is an elegant solution to the volume problem. Logging every token would make the Redis Stream very large for long responses; not logging any token-related events would make replay unable to recover partial content. The snapshot approach finds the middle ground.

---

## 9. Redis-Backed Dictionary (RedisDict)

### 9.1 Design and Interface Compatibility

`RedisDict` (in `src/utils/redis_dict.py`) subclasses Python's built-in `dict` but routes all reads and writes to a Redis Hash, keeping the internal CPython dict storage permanently empty. The goal is to be a drop-in replacement for `dict` for code that does `isinstance(x, dict)` — which many tool files do when checking for session memory.

```
Figure 9.1 — RedisDict Operation Routing

  memory["foo"] = "bar"
       │
       ▼
  RedisDict.__setitem__("foo", "bar")
       ├── HSET session:{id}:memory  foo  bar    (atomic, no reload needed)
       └── if on_change: on_change("foo", "modified")

  val = memory["foo"]
       │
       ▼
  RedisDict.__getitem__("foo")
       └── HGET session:{id}:memory  foo         (single Redis round-trip)

  del memory["foo"]
       │
       ▼
  RedisDict.__delitem__("foo")
       ├── HDEL session:{id}:memory  foo
       └── if on_change: on_change("foo", "deleted")
```

The implementation overrides every dict method that CPython might bypass (e.g., `get`, `keys`, `values`, `items`, `pop`, `setdefault`, `update`, `clear`, `copy`) to ensure they all go through Redis. This is a necessary but verbose requirement of subclassing `dict` in CPython.

### 9.2 The on_change Callback

The `on_change` callback is the mechanism by which session memory mutations automatically push UI updates. In `_load_session`, the callback is wired to emit two Socket.IO events:

```python
def _on_memory_change(key: str, event_type: str) -> None:
    keys = r.hkeys(mem_hash_key)
    socketio.emit("session_memory_keys_update", {"keys": keys}, room=session_id)
    socketio.emit("session_memory_key_event", {"key": key, "type": event_type}, room=session_id)
```

This fires on every `memory["key"] = value` or `del memory["key"]` call, anywhere in the codebase. Tool files do not need to know that they're writing to a live-updating UI — they just write to the dict as normal.

**Why this is significant:** The alternative approach — having the agentic loop check after each tool call whether memory changed and manually emit updates — would require every tool to report its own side effects, or require the loop to take a before/after snapshot and diff it. The callback approach is automatic and correct by construction: the emission is coupled directly to the mutation.

### 9.3 Limitations and Safety Notes

The docstring and code explicitly document several limitations:

- `dict(instance)` and `copy.copy(instance)` bypass `__iter__`/`__getitem__` at the C level and return an empty plain dict. Code that needs a snapshot must call `.to_dict()`.
- TTL management is the caller's responsibility — `RedisDict` never expires its own key.
- Values must be strings (matching Redis's RESP decode and session memory's contract).

---

## 10. EmittingKVManager: Reactive Project Memory

While session memory is backed by `RedisDict`, project memory is backed by MySQL. The `EmittingKVManager` plays the same reactive role for project memory: it wraps a MySQL `KVManager` and emits Socket.IO events after mutations.

```
Figure 10.1 — EmittingKVManager Operation

  emitting_kv.set_value("summary", "...", project="/home/user/myproject")
       │
       ▼
  1. Acquire short-lived DB connection from pool
  2. KVManager.set_value(key, value, project=project)
  3. conn.commit()
  4. keys = KVManager.list_keys(project=project)
  5. Release connection
  6. socketio.emit("project_memory_keys_update", {keys}, room=session_id)
  7. socketio.emit("project_memory_key_event", {key, type="modified"}, room=session_id)
```

Key design choices:

- **No persistent connection.** Each operation opens a connection from the pool and releases it when done. This avoids holding a connection open across the long-running agentic loop.
- **Only project-scoped operations emit.** Global KV store operations (project=None) are silently delegated without emitting, since the UI panel only shows project memory.
- **Injected via `special_resources`.** Tools receive `EmittingKVManager` via the `special_resources["emitting_kv_manager"]` dict. Tools that don't need it ignore it; tools that write project memory use it. This separation keeps tool files free of SocketIO dependency.

---

## 11. Frontend Architecture

### 11.1 Session Identity and Socket Lifecycle

The frontend (in `ui/src/components/Chat.tsx`) manages session identity and socket connection with careful attention to React's lifecycle rules.

**Session ID** is computed once per component mount, idempotently:
```typescript
const [sessionId] = useState<string>(() => {
    let id = sessionStorage.getItem('session_id')
    if (!id) { id = crypto.randomUUID(); sessionStorage.setItem('session_id', id) }
    return id
})
```

The `useState` initializer function runs exactly once, on mount. It reads from `sessionStorage` first — if an ID exists (same tab, after a page refresh), it is reused. If not (new tab), a UUID is generated. This means the session ID is stable across refreshes of the same tab, but different tabs get different IDs.

**Socket** is created via a `useRef` guard:
```typescript
const socketRef = useRef<Socket | null>(null)
if (!socketRef.current) { socketRef.current = createSocket(sessionId) }
const socket = socketRef.current
```

The `createSocket(sessionId)` factory creates a socket.io-client with `autoConnect: false`. The socket only connects when `socket.connect()` is called — which happens at the end of the `useEffect` that registers all handlers:

```
Figure 11.1 — Socket Handler Registration Order (Critical)

  useEffect(() => {
    // 1. Register all event handlers
    socket.on('connect', onConnect)
    socket.on('session_state', onSessionState)
    socket.on('event_replay', onEventReplay)
    socket.on('token', onToken)
    ... (all other handlers)

    // 2. THEN connect (never before all handlers are installed)
    socket.connect()

    return () => {
      // Cleanup: remove all handlers, disconnect
      socket.off('connect', onConnect)
      ...
      socket.disconnect()
    }
  }, [socket, applyReplayEvent, updateTurn])
```

This ordering is a correctness guarantee: the `connect` event — which triggers `resume_session` — can only fire after every handler is installed.

### 11.2 Thread State Model

The frontend holds a `thread: Turn[]` array as its primary state. Each `Turn` in this array mirrors the backend `Turn` structure, plus additional live-state fields:

```typescript
interface Turn {
    id: string
    userText: string
    exchanges: LLMExchange[]
    todoItems: TodoItem[]
    approvalItem?: ApprovalItem
    impossible?: string
    completed: boolean
    // Live state — only meaningful on current turn:
    streaming: boolean
    isInterimStreaming: boolean
    interimCharCount: number
    interrupted?: boolean
}
```

The `streaming`, `isInterimStreaming`, `interimCharCount`, and `interrupted` fields are frontend-only — they are not stored on the backend. They allow the `TurnContainer` component to render different states:

| State combination | UI rendering |
|-------------------|-------------|
| `streaming=true, !isInterimStreaming, no content` | `…` placeholder |
| `streaming=true, isInterimStreaming` | Interim char count badge |
| `streaming=true, !isInterimStreaming, has content` | Live streaming text (cursor active) |
| `streaming=false, completed=true` | Final static content |
| `interrupted=true` | "Connection interrupted" notice |

### 11.3 The Replay Processor

`applyReplayEvent(type, data)` is a `useCallback` that applies a single replay event to the `thread` state. It is the single source of truth for how events modify state — both the live handlers and the replay path call into it (though the live handlers also handle things like `updateLastEventId` and some live-only logic before delegating).

The replay processor handles:
- `turn_start` → appends a new (non-streaming) Turn
- `replay_content_snapshot` → sets accumulated content on a specific exchange
- `tool_call` → adds a ToolCallRecord to the last exchange, creating one if needed
- `tool_result` → finds the ToolCallRecord by ID and sets its result
- `begin_interim_stream` / `begin_final_summary` → toggle `isInterimStreaming`
- `todo_list_update` → updates `todoItems`
- `approval_request` / `approval_resolved` / `approval_timeout` → update `approvalItem`
- `message_done` → finalizes the turn (completed=true, streaming=false)
- `error` → writes error message into the last exchange

### 11.4 Live Event Handlers

The live event handlers (registered with `socket.on(...)`) perform two actions in addition to calling into `applyReplayEvent`-equivalent logic:

1. **Update `lastEventId`** — every event with an `event_id` field calls `updateLastEventId()`, which persists to `sessionStorage`. This keeps the replay cursor current.
2. **Token streaming** — `onToken` is handled separately because tokens are not logged to the stream and have special logic: if the last exchange already has tool calls (meaning a new LLM call started), a new exchange is created; otherwise the token is appended to the last exchange's `assistantContent`.

---

## 12. Event Replay and Reconnect Resilience

### 12.1 The lastEventId Cursor

The `lastEventId` stored in `sessionStorage` is a Redis Stream ID. It is updated after every event the frontend processes that has an `event_id` field. On reconnect, it is sent to the server in `resume_session { lastEventId }`.

```
Figure 12.1 — lastEventId Update Points

  Each live event with event_id:
    onTurnStart, onToolCall, onToolResult, onBeginInterimStream,
    onBeginFinalSummary, onMessageDone, onError, onApprovalRequest,
    onApprovalResolved, onApprovalTimeout, onReportImpossible,
    onTodoListUpdate
    → all call: sessionStorage.setItem('lastEventId', data.event_id)

  onEventReplay:
    → after processing all replayed events:
      sessionStorage.setItem('lastEventId', events.last.id)
```

This cursor is accurate because it uses the Redis Stream ID (millisecond timestamp with sequence), not a sequential counter. If the server is restarted and the Redis Stream is empty, the cursor from `sessionStorage` will simply return no events (the `XRANGE` call returns an empty list), which is handled gracefully.

### 12.2 Animated vs. Fast Replay

When `onEventReplay` receives a batch of events, it checks whether animating them one by one would take more than `REPLAY_ANIMATION_MAX_TIME = 2000ms` at `REPLAY_EVENT_DELAY = 64ms` per event:

```
threshold = floor(2000 / 64) = 31 events
```

- **≤ 31 events:** Each event is processed via `setTimeout(applyOne, i * 64)`. This spreads the state updates across 2 seconds, making the reconnect experience visually show the conversation building up. No loading indicator is shown — the animation itself communicates progress.

- **> 31 events:** The loading modal is shown, all events are processed synchronously in a single `setTimeout(processAll, 16)` (one frame later, to give React time to render the modal), then the modal is dismissed.

```
Figure 12.2 — Replay Path Decision Tree

  events received
       │
       ├── events.length == 0 → return (no-op)
       │
       ├── events.length <= 31
       │       → no modal
       │       → for each event i: setTimeout(applyOne, i * 64ms)
       │           (gradually reveals the replay, like a fast-forward)
       │
       └── events.length > 31
               → setIsLoadingBackendState(true)
               → setTimeout(16ms) {
                   for all events: applyOne(ev) synchronously
                   setIsLoadingBackendState(false)
                 }
```

**Design justification:** The user asked for "replay animation as feedback" vs. "loading modal as feedback". The threshold at 31 events (≈2 seconds of replay time) ensures the animation is only used when it completes in a reasonable time. For a reconnect during a 100-step tool run, jumping straight to the final state with a loading indicator is clearly better UX than a 6-second animation.

### 12.3 In-Progress Turn Restoration

When `onSessionState` arrives and `currentTurn` is non-null (the agent was running when the tab refreshed), the frontend:

1. Constructs the Turn from the serialized data (using `backendTurnToFrontendTurn`)
2. Sets `streaming: true` and `interrupted: false` on it
3. Appends it to the `thread` array
4. Sets `busy: true`

Then `onEventReplay` fires — if there are events, they fill in the details of the in-progress turn (additional tool calls, results, content snapshots). If the agent already finished while the tab was closed, `message_done` will be among the replayed events, which sets `streaming: false` and `completed: true`, completing the picture.

If the agent was running but there are no replayed events (e.g., last event ID is current), the turn displays as `streaming=true` with whatever content was saved in the last checkpoint. The live `token` events from the still-running agent will continue to arrive in real time.

---

## 13. Session Storage and Scroll Persistence

The browser's `sessionStorage` is used for three categories of data:

| Key | Value | Purpose |
|-----|-------|---------|
| `session_id` | UUID string | Stable session identity across page refreshes |
| `lastEventId` | Redis Stream ID (e.g. `"1740929012345-0"`) | Replay cursor |
| `scroll:{persistId}` | Integer (scroll position in px) | Per-container scroll restoration |

**`sessionStorage` vs `localStorage`:** `sessionStorage` is scoped to a single browser tab. A new tab gets a new session and starts fresh. `localStorage` is shared across tabs of the same origin. The choice of `sessionStorage` means each tab has its own independent agent session — the intended behavior.

**Scroll persistence** is implemented in `useScrollToBottom` with a `persistId` parameter. When set:
- On mount (`useLayoutEffect`): reads `scroll:{persistId}` from `sessionStorage` and applies it to `el.scrollTop`, then checks whether that position is "at the bottom" to set `isAtBottom`.
- On scroll: debounces writes to `sessionStorage` (200ms debounce) to avoid writing on every scroll event.
- On unmount: cancels any pending debounced write.

The `useLayoutEffect` (not `useEffect`) is used for the restore because scroll position must be applied to the DOM before the browser paints — if applied after paint, users see a flash of the wrong scroll position.

```
Figure 13.1 — Scroll Persistence State Machine

  MOUNT:
    read sessionStorage → apply scrollTop → set isAtBottom

  USER SCROLLS UP:
    isAtBottom = false
    cancel pending throttled scroll-to-bottom
    (debounced) write scrollTop to sessionStorage

  USER SCROLLS DOWN (reaching bottom threshold):
    isAtBottom = true
    (debounced) write scrollTop to sessionStorage

  NEW CONTENT ARRIVES (agent streaming):
    scrollToBottomIfNeeded() → only scrolls if isAtBottom == true
    (prevents hijacking user's manual scroll position)

  UNMOUNT:
    cancel debounced write
    cancel throttled scroll
```

---

## 14. Loading Modal

The loading modal appears in two scenarios:

1. **Initial session load** (`onConnect` → until `onSessionState` arrives): The browser connected, sent `resume_session`, and is waiting for the server to load the Redis session and respond. Duration is typically <100ms on a local server, but can be longer on slow connections or cold Redis.

2. **Large event replay** (> 31 events in `onEventReplay`): Enough events arrived to make animated replay impractical; the modal shows while they are applied synchronously.

```
Figure 14.1 — Loading Modal Render Conditions

  isLoadingBackendState=true:  ┌────────────────────────────────┐
                               │                                │
                               │  ████████████████████████████ │ ← backdrop
                               │  ██                        ██ │
                               │  ██   ┌────────────────┐   ██ │
                               │  ██   │  ⟳             │   ██ │
                               │  ██   │  (blue spinner) │   ██ │
                               │  ██   │                │   ██ │
                               │  ██   │  loading       │   ██ │
                               │  ██   │  backend       │   ██ │
                               │  ██   │  state...      │   ██ │
                               │  ██   └────────────────┘   ██ │
                               │  ██   white, 16px radius    ██ │
                               │  ████████████████████████████ │
                               └────────────────────────────────┘
```

The modal is rendered at `z-index: 2000` (above the existing tool-result viewer modal at `z-index: 1000`) and uses `position: fixed; inset: 0` to cover the full viewport. The card itself is white (`#ffffff`) with `border-radius: 16px` and a strong `box-shadow`, consistent with modern modal design conventions.

The modal is intentionally non-dismissible (no close button, backdrop click does nothing). This is correct because there is no meaningful user action during loading — the session data is either coming or it isn't. Making it dismissible would allow the user to interact with an inconsistent (empty) state.

---

## 15. Innovations and Design Highlights

This section highlights design decisions that are non-obvious, unconventional, or that solve problems in ways not commonly seen in chat/agent UI systems.

### 15.1 Stable Session IDs Decoupled from WebSocket SIDs

Most Socket.IO-based agent UIs use the server-assigned SID as the session key. This system generates a UUID in the browser and uses that as the session key, with the SID as a transient routing artifact only. This is arguably the correct inversion of ownership: the session belongs to the user (the browser), not to the transport layer.

**Consequence:** Disconnecting never destroys state. The agent can complete a tool run while the browser is offline. The user can close the tab and return within the TTL window to find the conversation intact.

### 15.2 Redis Streams as a Lightweight Event Sourcing Log

Using Redis Streams as an append-only event log for reconnect replay is an innovative application of a data structure usually discussed in the context of message queues and consumer groups. Here it is used simply as a sequential log with cursor-based reads — no consumer groups, no acknowledgements, no pub/sub. The auto-generated Stream IDs (millisecond timestamps with sequence numbers) serve as natural, globally-ordered cursors that the client can store and send back.

**This approach is rare** because most systems either (a) store no replay log at all (resulting in lost state on disconnect), (b) store the full message history in the session blob (which is loaded and sent as one payload), or (c) use a separate persistent message bus (Kafka, RabbitMQ) which is heavy infrastructure. Using Redis Streams keeps the event log co-located with the session data, uses a single Redis connection, and expires automatically with the same TTL as the rest of the session.

### 15.3 replay_content_snapshot as a Content Recovery Mechanism

The dual design of excluding `token` events from the stream (volume) but periodically snapping content (recoverability) is an elegant engineering trade-off. It is conceptually similar to how video compression works: rather than storing every frame, store keyframes (snapshots) and delta frames (tokens). On replay, apply the most recent keyframe. The "worst-case" loss is 50 tokens of content — entirely acceptable for a reconnect scenario where the user will see the rest of the conversation as it streams in.

### 15.4 user_continuation on LLMExchange

The `user_continuation` field on `LLMExchange` is a subtle but important data model innovation. It allows the structured message history to carry injected follow-up user prompts (unclosed-todo reprompts, final-summary requests) in exactly the right position — embedded within the exchange that precedes them. This is the only correct way to handle these injections when serializing and deserializing the turn history for replay, because it preserves the invariant that `tool` messages always immediately follow their `assistant` counterpart.

An alternative approach — appending injected messages to a flat list alongside the tool messages — would either require complex positional bookkeeping during serialization, or break the OpenAI message format requirements on deserialization.

### 15.5 RedisDict as a Transparent Drop-In for dict

The `RedisDict` subclasses Python's `dict` specifically to pass `isinstance(x, dict)` checks in legacy tool code. This is a pragmatic compatibility layer — rather than auditing and refactoring every tool file that checks `isinstance(memory, dict)`, a single class provides Redis-backed semantics behind the familiar dict interface.

The `on_change` callback wired to live Socket.IO emission creates a genuinely reactive memory UI with zero polling and zero tool-side coupling. A tool writes `memory["key"] = value`; the UI automatically updates. This pattern — using Python's object model to intercept mutations at the storage layer — is more typically seen in ORM systems (SQLAlchemy's unit-of-work pattern) than in agent memory systems.

### 15.6 Animated vs Fast Replay — Threshold-Gated

The threshold-gated replay animation (`REPLAY_EVENT_DELAY = 64ms`, `threshold = floor(2000/64) = 31 events`) provides adaptive UX: for short reconnects (few missed events), an animation provides natural, reassuring feedback without a loading indicator. For long reconnects (many missed events), an explicit loading indicator replaces the animation, avoiding an uncomfortably long "fast-forward" animation that would feel broken. The threshold is a pure constant — tunable — which means the behavior can be adjusted without structural changes.

### 15.7 Approval Gate with Automatic Release on Disconnect

The design of `_request_approval` — using `threading.Event.wait(timeout=60)` combined with `handle_disconnect` setting `approved=False` and calling `event.set()` — guarantees forward progress under all disconnect conditions. This is not a trivial correctness property: many approval-gate implementations either hang forever (no timeout), fail to release on disconnect (the release code is in the wrong handler), or lose the approval state on reconnect (new connection doesn't know about the pending approval).

In this system, the disconnect immediately resolves the approval as denied — the agentic loop proceeds cleanly. On reconnect, `event_replay` will include the `approval_resolved` event with `approved=false`, so the UI correctly reflects what happened.

---

*End of report.*

**Files referenced:**
- `src/ui_connector/app.py` — Flask/SocketIO initialization
- `src/ui_connector/socket_handlers.py` — All socket event handlers and agentic loop
- `src/utils/session_model.py` — Session/Turn/LLMExchange/ToolCallRecord data classes
- `src/utils/event_log.py` — Redis Streams log_event / get_events_since
- `src/utils/redis_dict.py` — RedisDict (Redis-backed dict subclass)
- `src/utils/emitting_kv_manager.py` — EmittingKVManager (reactive MySQL-backed KV)
- `ui/src/socket.ts` — Socket factory
- `ui/src/types.ts` — Frontend Turn/LLMExchange/ToolCallEntry TypeScript interfaces
- `ui/src/components/Chat.tsx` — Main frontend component
- `ui/src/hooks/useScrollToBottom.ts` — Direction-aware auto-scroll with persistence
