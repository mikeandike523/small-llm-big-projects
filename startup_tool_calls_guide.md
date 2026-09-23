# Startup Tool Calls Guide

How `startup_tool_calls.json` works: what it can call, how (and when) it's
validated, and how its execution environment differs from a normal in-turn
tool call — including redaction, where writing an entry stands in for a
human's approval rather than being treated as unapproved.

This guide describes the implementation in
`src/ui_connector/socket_handler_components/http_api.py`
(`api_create_session`), `src/utils/startup_tool_calls.py`
(`validate_startup_tool_calls`), and
`src/ui_connector/socket_handler_components/socket_events.py`
(`handle_run_startup_tool_calls`). Read `./custom_tool_guide.md` and
`./custom_skill_guide.md` first if you haven't — this feature calls the
tools those guides teach you to author.

---

## 1. What it is, and when it runs

`startup_tool_calls.json` is a flat, ordered list of tool calls to run
automatically, once, right after a session's first connection — a bootstrap
sequence (load a config, prime session memory, check a connection) that runs
before the agent sees the first user message.

- Enabled via `slbp session new --load-startup-tool-calls --cwd <dir>`
  (on by default), which sets
  `startup_tool_calls_path = <dir>/startup_tool_calls.json`
  (`src/cli_routes/session.py`). Same `{cwd}`-relative convention as
  `skills/` and `tools/`. A missing file is not an error — it's silently
  treated as "no startup calls."
- Runs exactly **once per session**, gated by `session.startup_done`
  (persisted). The frontend requests it (`run_startup_tool_calls` socket
  event) right after connecting, if `startup_done` is still false; the
  handler is a no-op (emits `{skipped: true}`) if it's already run.
- Each call's result is emitted to the UI (`startup_tool_call` /
  `startup_tool_result` events, rendered by `StartupToolsCard`) — the agent
  itself never sees these results directly; they're a visible pre-flight
  step, not part of the LLM conversation.

---

## 2. File format

```json
[
  { "name": "get_environment_info", "args": {} },
  { "name": "session_memory", "args": { "action": "set", "key": "project", "value": "..." } },
  { "name": "my_plugin_do_thing", "args": { "target": "x" } }
]
```

- Top level must be a JSON array.
- Each entry is an object with a required `name` (string) and optional
  `args` (object, defaults to `{}`).
- `name` is the tool's **final** name — exactly as it appears in the
  session's tool set, namespace prefix included for a skill-scoped custom
  tool (e.g. `my_plugin_do_thing`, not `do_thing`). See
  `custom_tool_guide.md` §2/§5 for how that name is derived.
- Calls run in array order, sequentially, synchronously — there's no
  parallelism and no conditional branching.

---

## 3. Which tools are callable — the answer is "all of them"

Startup calls run **before any turn or skill selection has happened**, so
the skill-gating from `custom_tool_guide.md` §6 doesn't apply here: there's
no "active skill" concept yet to narrow against. The tool map used
(`_get_session_tool_map`) is the session's **full validated manifest** —
every built-in, every unscoped custom tool, and every skill-scoped plugin's
tools, regardless of whether that skill would ever actually be selected in
this session's conversation. A skill-scoped tool is just as callable here as
an unscoped one; the only thing that matters is that it loaded successfully
at session creation.

---

## 4. Validation — hard-fails session creation, same as tools/skills

`startup_tool_calls.json` gets the same guarantee custom tools and custom
skills already have: a broken config **fails session creation outright**
(`POST /api/sessions` returns `400`, no session is created) rather than
failing softly the first time it actually runs. This is
`validate_startup_tool_calls` (`src/utils/startup_tool_calls.py`), called
from `api_create_session` right after the full tool manifest is built (so it
has every custom tool's real `DEFINITION` to check against), before the
session is saved. It checks, in order, for the first entry that fails:

1. The top-level value is a JSON array.
2. Every entry is an object.
3. Every entry has a non-empty string `name`.
4. `name` exists in the session's full tool map (§3) — an unknown name
   (typo, wrong namespace, referencing a tool from a `tools/` plugin that
   itself failed to load) is rejected with a message naming the bad entry.
5. `args`, if present, is an object.
6. `args`, **excluding reserved framework params** (`request_unredacted` —
   see §5), passes `validate_tool_args(module.DEFINITION, args)` — the exact
   same JSON-Schema-subset check a real tool call gets
   (`custom_tool_guide.md` §4): required properties present, no unknown
   properties when `additionalProperties: false`, correct types/enums/etc.
   `request_unredacted` itself isn't schema-checked, same as it never is for
   a normal tool call — it's a framework-managed flag, not part of any
   tool's own declared schema.

What this validation does **not** do: actually execute anything, or
guarantee success. A call that's structurally and schematically valid can
still fail for environmental reasons at real execution time (a file that
doesn't exist yet, a network call that times out) — that's a runtime
concern, surfaced as a string result (§6), not something creation-time
validation can know about.

---

## 5. Redaction: writing the entry IS the approval

Startup tool calls go through the exact same `execute_tool` function a
normal turn's tool calls do, so a tool with `ENABLE_REDACTION = True`
(`custom_tool_guide.md` §10) gets its result redacted here identically —
**including the bypass.**

`startup_tool_calls.json` is hand-authored by a human who already has
filesystem access to the project. Writing `"request_unredacted": true` into
an entry's `args` **is** that human's approval for it — the same act as
clicking Approve on an interactive prompt for a normal tool call, just given
in advance instead of in the moment. So it's honored exactly as it would be
for an already-approved call:

- Honored only if the target tool actually supports the bypass, i.e. it set
  `ENABLE_REDACTION = True` and did *not* set
  `ALLOW_REQUEST_UNREDACTED = False` (`custom_tool_guide.md` §10) — a tool
  that refuses the bypass entirely refuses it here too, same as everywhere
  else. There's no startup-specific override of that flag in either
  direction.
- Not schema-validated (§4, step 6) — like any reserved framework param, it
  isn't part of the tool's own `DEFINITION`, so it's excluded before
  `validate_tool_args` runs, exactly like a normal call.
- Not stripped or blocked anywhere in `handle_run_startup_tool_calls` —
  `args` reaches `execute_tool` unmodified, and `execute_tool`'s normal
  `enable_redaction and allow_unredacted and requested_unredacted` logic
  decides the outcome, unaware (and uninterested in) whether the call came
  from a turn or from startup.

This is deliberate, not an oversight: treating "no interactive prompt at
this exact moment" as "no human approved it" would be wrong here — the
human's approval already happened, at the moment they wrote the file. See
§6 for the same reasoning applied to approval more generally.

---

## 6. How execution differs from a normal in-turn tool call

`handle_run_startup_tool_calls` calls `execute_tool` **directly** — it does
not go through `_execute_tools` (`tool_execution.py`), the function that
handles normal turn tool calls. That skips several things:

- **No interactive approval gate.** `needs_approval` (`custom_tool_guide.md`
  §8) is never consulted. This isn't a hole — the file itself already *is*
  the approval, given in advance by the human who wrote it (same reasoning
  as `request_unredacted` in §5). A tool that would normally prompt the
  user — `host_shell`, any file-editing tool outside the approved CWD,
  anything — runs unconditionally, because writing the entry was the act of
  approving it. Configure it like you'd configure any other trusted startup
  script: everything in the file runs, no second confirmation.
- **No dirty-cache tracking.** `dirty_effects` (`custom_tool_guide.md` §9)
  is declared but never consulted — nothing gets marked dirty/clean, and
  `requires_clean_*` gates never block a startup call.
- **No auto-snapshot.** Writing a file here does not trigger the
  before-first-write snapshot that a normal in-turn write does
  (`src/tools/_file_snapshot.py`).
- **No result stubbing.** Long results are still truncated per-line
  (`TOOL_OUTPUT_MAX_COLUMNS`, applied inside `execute_tool` itself — this
  part is identical), but the "stub into session memory with a preview"
  behavior (`NO_STUB`, `custom_tool_guide.md` §7) only exists in
  `_execute_tools` and never runs here.
- **A smaller `special_resources`.** Only these keys are populated:
  `emit_backend_log`, `session_init_working_dir`, `session_current_working_dir`,
  `approval_mode`, `create_file_auto_eol`, `on_cwd_change`, and
  `request_unredacted` (the resolved bypass decision — §5). Everything else
  from the full reference table in `custom_tool_guide.md` §11 — `on_chunk`,
  `cancel_event`, `llm`, the terminal integration callables, the sampler
  callbacks — is simply **absent from the dict**, not present-but-`None`.
  A tool that unconditionally indexes one of those
  (`special_resources["on_chunk"]` instead of
  `special_resources.get("on_chunk")`) will raise `KeyError` if it's ever
  used as a startup call. Write tools defensively (`.get(...)`, as the
  built-ins already do) if they might run in both contexts.
- **Redaction still applies, bypass included.** Covered fully in §5 — this
  is the one thing that behaves fully identically to a normal, approved
  turn's tool call, not a reduced version of it.

A runtime failure (an exception, or the tool's own `"Error: ..."` string
return) does not fail the session — it's caught
(`except Exception as exc: result = f"Error executing '{name}': {exc}"`),
surfaced as that call's result in the UI, and the loop continues to the next
call. `session.startup_done` is set `True` regardless of whether any
individual call failed.

---

## 7. Pre-flight checklist

- [ ] Top-level JSON value is an array.
- [ ] Every entry has a `name` matching a real, final (namespaced if
      skill-scoped) tool name for this session's loaded tool set.
- [ ] `args` (if present) is an object that satisfies that tool's
      `DEFINITION` schema — required properties present, no extra
      properties if the tool sets `additionalProperties: false`.
- [ ] Anything that would normally need approval (writes, shell, network, or
      `request_unredacted`) is intentional — writing the entry is itself the
      approval, with no interactive confirmation to catch a mistake (§5, §6).
- [ ] `request_unredacted: true`, if used, is only set where actually
      needed — it's honored exactly as an approved normal call would honor
      it (subject to the target tool's `ALLOW_REQUEST_UNREDACTED`), not
      schema-checked, so a typo'd or unnecessary value won't be caught by
      validation.
- [ ] If a targeted tool reads `special_resources` beyond the reduced set in
      §6, it accesses those keys with `.get(...)`, not direct indexing.
- [ ] Order matters if calls depend on each other's side effects (e.g. one
      call priming a `session_memory` key another call's arguments assume
      exists) — they run strictly in array order.
