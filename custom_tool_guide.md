# Custom Tool Guide

How to write custom tool plugins for `slbp`, what the loader requires for a
tool to be *compliant* (loads without error) and *complete* (behaves like a
first-class tool — approvals, redaction, dirty-tracking, etc. all work), how
imports resolve inside custom tool code, and how to wrap/compose another
tool (§11).

This guide describes the loading scheme as implemented in
`src/tools/__init__.py` (`load_custom_tools`) and the tool-execution contract
in `src/ui_connector/socket_handler_components/tool_execution.py`. When in
doubt, those two files are the source of truth — this guide just organizes
what they already enforce.

Custom tools are **session-scoped**, loaded once at session-creation time
(`POST /api/sessions`), not at server startup. Each new session re-reads the
`tools/` directory — and, as of the live-reload feature below, an existing
session can now re-read it too, without restarting.

**This is now a coupled system with custom skills, not two independent
ones.** A skill-scoped tool plugin's tools are only offered to the LLM on
subturns where its matching skill is active — see §6, and read
`./custom_skill_guide.md` alongside this guide if you haven't already.

### Live reload (no new session needed)

The same reload endpoint described in `custom_skill_guide.md`'s intro
(`POST /api/sessions/<id>/reload-custom-skills-tools`, wired to a sync-icon
button in the session header) also refreshes this session's custom tools.
Internally (`reload_custom_tools` in `src/tools/__init__.py`, backed by
`src/tools/_custom_tool_reload.py`) it:

- Evicts every previously-loaded module that belongs to this session's
  `tools/` directory from `sys.modules` — both the session-prefixed tool/
  plugin modules (§5) *and* any helper module a tool file pulled in via
  `import_local` (§13.2) from somewhere under that same directory — then
  re-runs the normal `load_custom_tools` load from scratch, so edited source
  (including edited helpers) is actually re-executed rather than served from
  a cached module object.
- Re-validates everything exactly as a fresh session creation would (§5's
  collision rules, §6's skill-gating, etc.). If validation fails, the old
  modules are restored into `sys.modules` and the session's previous tool
  set is left in place untouched — a bad edit never leaves a session with
  half-loaded or missing tools.
- Is rejected outright (`409`) if a turn is currently active on the session,
  or if the session wasn't started with `--load-custom-skills-tools`.

This doesn't change anything about how you *write* a tool — it just means
you no longer need a brand-new session to see edits to existing files, or to
have a brand-new tool file/plugin folder recognized at all (session creation
used to be the only time the tool set was ever discovered from disk).

---

## 1. Directory layout

```text
<project-cwd>/
  tools/
    __init__.py                  # optional: runs once, before any plugin loads
    _exclude_builtin_tools.py    # optional: disable specific built-in tools
    root_tool.py                 # unscoped: no namespace, always active
    my_plugin/                   # skill-scoped plugin
      __init__.py                # required (content now optional — see §2)
      do_thing.py                # a tool (has DEFINITION + execute)
      _helpers.py                # a helper module (no DEFINITION — not a tool, see §3)
    another_plugin/
      __init__.py
      ...
```

- `tools/` is enabled together with custom skills via
  `slbp session new --load-custom-skills-tools --cwd <dir>`. The session core
  always derives the directory as `<dir>/tools`; arbitrary paths are not
  accepted (see §13 on imports, where the path matters).
- Three loadable categories, all validated together at session creation:
  1. **Unscoped tools** — `.py` files directly in `tools/` (excluding the two
     reserved filenames below). No namespace prefix; the tool's final name is
     its bare `DEFINITION['function']['name']`. Always included in every
     subturn's tool set, independent of skill selection.
  2. **Skill-scoped plugins** — immediate subdirectories of `tools/` that
     contain an `__init__.py`. Every tool file in one is namespace-prefixed
     and only active while its matching skill is active — see §2 and §6.
     Subdirectories without an `__init__.py` are ignored. Both categories are
     discovered in sorted order, and this scan is exactly one level deep —
     files nested further inside a plugin folder are not scanned as tools.
  3. Files without a top-level `DEFINITION` attribute, in either category,
     are silently treated as **helper modules**, not tools (see §3).
- `tools/__init__.py` (directly under `tools/`, not inside a plugin) is
  optional and runs exactly once per session, before anything else is loaded —
  the intended use is adding a vendored dependency directory to `sys.path`.
  It is not itself scanned as an unscoped tool file.
- `tools/_exclude_builtin_tools.py` is optional and lets a session disable
  specific **built-in** tools (not custom ones). Format:

  ```python
  EXCLUDE: dict[str, dict] = {
      "brave_web_search": {"loading": True},
  }
  ```

  Only the `"loading"` flag is honored here (the `"testing"` flag exists for
  the repo's own root-level `src/tools/_exclude_builtin_tools.py`, used by
  `tool_tests/`, and has no effect on a session's custom exclude file).

---

## 2. Anatomy of a plugin `__init__.py`

`TOOL_NAMESPACE` is **optional**:

```python
TOOL_NAMESPACE = "my_plugin"   # optional — defaults to the plugin's folder name
```

If omitted, the plugin's namespace defaults to its **folder name**. An
explicit `TOOL_NAMESPACE` overrides that default (e.g. for a folder name that
isn't a valid/desired namespace string). Either way, every tool this plugin
defines is exposed to the LLM as
`f"{tool_namespace}_{DEFINITION['function']['name']}"`. For example, a tool
file with `DEFINITION.function.name == "do_thing"` inside a plugin folder
named `my_plugin` (no explicit `TOOL_NAMESPACE`) becomes the callable tool
`my_plugin_do_thing`.

**The resolved namespace must match a known skill id** (built-in or custom,
from this same session's skill registry) — see §6. This is the one thing
that still hard-fails session creation the way a missing `TOOL_NAMESPACE`
used to.

The `__init__.py` file itself must still exist (that's what makes a folder a
plugin at all — see §1) but its *content* is now fully optional; an empty
file is valid as long as the folder name happens to match a skill id.

Anything else the `__init__.py` does (imports, setup code, `sys.path`
manipulation local to this plugin) runs once when the plugin is discovered.

---

## 3. Anatomy of a tool file

A minimal, compliant tool file:

```python
from __future__ import annotations

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "do_thing",
        "description": "Does a thing.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "What to do the thing to.",
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    },
}


def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    return f"Did the thing to {args['target']!r}."
```

Two things are load-time requirements:

1. **`DEFINITION`** must be present as a module-level attribute for the file
   to be treated as a tool at all (absence just means "this is a helper file,
   skip it" — not an error). This applies identically to unscoped root-level
   files and files inside a skill-scoped plugin.
2. **`execute`** must exist once `DEFINITION` is present. A `DEFINITION`
   without `execute` raises `RuntimeError` at load time.

Everything else (`needs_approval`, `dirty_effects`, `ENABLE_REDACTION`,
`NO_STUB`, …) is optional, module-level, and described below.

---

## 4. The `DEFINITION` schema

`DEFINITION` is an OpenAI-style function-calling tool definition. The
project's validator (`src/utils/tool_calling/arguments.py:validate_tool_args`)
enforces a **subset** of JSON Schema against incoming arguments at call time —
write to this subset, since anything outside it is accepted syntactically but
never actually validated:

| Field | Notes |
|---|---|
| `type` | Must be the literal string `"function"`. |
| `function.name` | Required. This is the *base* name — the final callable name gets a namespace prefix prepended by the loader for skill-scoped plugins (unscoped tools use it verbatim — see §5). Don't include the namespace yourself. |
| `function.description` | Free text. This is the LLM's only guidance on when/how to call the tool — be as explicit as a built-in tool's description (see any file in `src/tools/` for the house style: explicit preconditions, mutually-exclusive-argument notes, examples). |
| `function.parameters.type` | Must be `"object"` — this is checked and will hard-fail (`ToolValidationError`) if wrong. |
| `function.parameters.properties` | Per-property schemas. Supported `type` values: `string`, `integer`, `number`, `boolean`, `object`, `array`, `null`. |
| `function.parameters.required` | List of required property names. |
| `function.parameters.additionalProperties` | Set `false` to reject unknown keys (recommended — matches every built-in tool). Omitted/`true` allows extras through unvalidated. |
| per-property `enum` | Value must be one of the listed values. |
| per-property `minLength`/`maxLength`/`pattern` | String constraints (`pattern` is a `re.search`, not full-match). |
| per-property `minimum`/`maximum` | Number/integer constraints. |
| nested `object` properties | One level of `properties`/`required`/`additionalProperties` is validated; deeper nesting is not. |

**Do not set `function.strict` yourself.** It's set automatically per-model by
`src/utils/tool_calling/strict_mode.py` based on the active dialect — write
normal `required`/optional properties and the framework handles strict-mode
transformation.

**Reserved parameter names — never declare these in `properties`:**

```python
_RESERVED_TOOL_PARAMS = {"request_unredacted"}
```

Declaring `request_unredacted` yourself raises `RuntimeError` at load time
(custom tools) or is checked separately for built-ins. This parameter is
injected automatically for tools that opt into redaction — see §10.

---

## 5. Naming and collision rules

- **Skill-scoped**: final tool name = `f"{tool_namespace}_{DEFINITION['function']['name']}"`
  (see §2 for how `tool_namespace` resolves).
- **Unscoped**: final tool name = `DEFINITION['function']['name']` verbatim —
  no prefix.
- If that name already exists — a built-in tool, an unscoped custom tool, or
  a tool from *any* skill-scoped plugin in this session, regardless of
  namespace — loading raises `RuntimeError`. Rename one of them. This check
  is global across all three categories, not scoped per-plugin.
- Each tool *file* is loaded as a Python module under a private, generated
  name (unscoped: `_slbp_{session_prefix}_{file_stem}`; skill-scoped:
  `_slbp_{session_prefix}_{tool_namespace}_{file_stem}`, where
  `session_prefix` is the first 8 chars of the session id). If that module
  name is already registered in `sys.modules`, loading raises `RuntimeError`
  telling you to rename the file. You will essentially never hit this by
  accident with sensible file names.

A load failure anywhere (a skill-scoped plugin's namespace not matching a
known skill id, missing `execute`, missing `function.name`, a name collision,
a reserved-param violation, a Python exception while importing the file)
aborts the **entire** `tools/` load for that session — `POST /api/sessions`
returns `400` with the `RuntimeError` message, and the session is never
created. There's no partial-load fallback, so one broken tool file blocks
everything else too. Test each new tool file in isolation before adding more.

---

## 6. Skill-gating — tools tied to a skill's activation

A skill-scoped plugin's namespace (§2) must equal a **known skill id** —
built-in or custom, from this session's fully resolved skill registry (see
`./custom_skill_guide.md` for how that registry and its ids are built). If
it doesn't, session creation hard-fails with an actionable error naming the
offending plugin and three ways to fix it: make the tools unscoped instead
(§1), add a matching skill (even empty/placeholder content is enough — see
`custom_skill_guide.md` §1), or rename the plugin/`TOOL_NAMESPACE` to an
existing skill id. This is deliberately a hard error, not a silent no-op —
a tool plugin nobody can ever reach is almost always a mistake, not an
intentional feature.

**What "active" means, per subturn:** exactly the same resolved skill
snapshot that decides which skill *guidance text* is injected that subturn
(autoloaded skills, this subturn's selector picks, plus their combined
dependency closure — see `custom_skill_guide.md` §5, §7). A plugin's tools are
in the LLM's `tools` array whenever, and only when, its matching skill is in
that snapshot:

- Attached to an **autoloaded** skill (`autoload: true`) → effectively always
  active, since an autoloaded skill never leaves the baseline active set for
  the life of the session.
- Attached to a **selector-visible** skill (the default, `autoload: false`)
  → active only on subturns where the selector actually picks that skill (or
  it's pulled in as another active skill's dependency). It can appear and
  disappear turn to turn.

This is recomputed **fresh every subturn — not sticky**. Once a skill stops
being active, its tools are simply absent from the next subturn's `tools`
array; there's no accumulation. The model has its own awareness of this
(see the `== DYNAMIC TOOL LIST ==` section of the system prompt,
`src/logic/system_prompt.py`) so it doesn't treat a since-vanished tool's
earlier appearance in the conversation as an error.

Unscoped tools (§1) sidestep all of this — they have no matching skill to be
tied to and are simply always present.

---

## 7. `execute` — the required entry point

```python
def execute(args: dict, session_data: dict, special_resources: dict | None = None) -> str:
    ...
```

- Called as `execute(clean_args, session_data)` or
  `execute(clean_args, session_data, special_resources)` — the framework
  inspects your function's signature (`inspect.signature`) and passes
  `special_resources` **only if your function declares 3+ parameters**. If you
  don't need it, omit the parameter entirely rather than accepting and
  ignoring it.
- `args` has already been schema-validated against `DEFINITION` and has the
  `request_unredacted` framework param stripped out — you never see it.
- `session_data` is the session's mutable state dict (persisted). Its
  `session_data["memory"]` sub-dict is the conventional home for the
  `session_memory_key` read/write pattern used throughout the built-in tools
  (see `write_text_file.py` for the canonical shape: accept either raw
  `content` or a `session_memory_key`, mutually exclusive).
- **Return a `str`.** There is no structured/JSON return channel — errors are
  communicated as strings, conventionally prefixed `"Error: ..."` (dirty-cache
  effects are skipped for any result starting with `"Error"` — see §9).
- Do not catch and swallow `ToolHangError`/`ToolTimeoutError` — let them
  propagate; the framework has dedicated handling for both (`src.utils.exceptions`).
- Long return values are automatically truncated per-line
  (`TOOL_OUTPUT_MAX_COLUMNS`) and, above a size threshold, "stubbed" into
  session memory with a preview (see `_stub_tool_result` in
  `tool_execution.py`). Set `NO_STUB = True` at module level to opt out for
  tools whose full output the agent must always see verbatim (used by
  `dom_analyzer.py`, `snapshot_file.py`, `restore_file.py`):

  ```python
  NO_STUB = True
  ```

### Progress streaming (optional)

If `special_resources` is accepted, `special_resources["on_chunk"]` is always
present during execution — call it with incremental text to stream progress
to the UI before your final return value is ready:

```python
def execute(args, session_data, special_resources=None):
    on_chunk = (special_resources or {}).get("on_chunk")
    if on_chunk:
        on_chunk("starting...\n")
    ...
    return "done"
```

---

## 8. `needs_approval` (optional)

```python
def needs_approval(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> bool:
    ...
```

- Optional — a tool with no `needs_approval` is never gated (always runs
  immediately). This is the default a plugin author almost never wants for
  anything that touches the filesystem, network, or shell — be deliberate
  about omitting it.
- Arity is flexible and introspected the same way as `execute`: 1, 2, or 3
  positional parameters are all accepted (`fn(args)`, `fn(args, session_data)`,
  or `fn(args, session_data, special_resources)`), matched by how many
  parameters your function declares.
- Return a `bool`. `True` means "prompt the user before running."
- `special_resources.get("approval_mode")` holds the session's live approval
  mode (`"default"`, `"auto-accept-edits"`, `"full-auto"`). Use the helpers in
  `src.tools._approval` to stay consistent with built-in behavior instead of
  hand-rolling the mode checks:

  ```python
  from src.tools._approval import (
      ApprovalContext,
      is_full_auto,
      is_auto_accept_edits,
      needs_path_approval,
  )

  def needs_approval(args, session_data=None, special_resources=None):
      if is_full_auto(special_resources):
          return False
      if is_auto_accept_edits(special_resources):
          return needs_path_approval(
              args.get("path"),
              ctx=ApprovalContext.from_special_resources(special_resources),
          )
      return True
  ```

  `needs_path_approval` auto-approves paths inside the session's current/
  initial CWD that aren't git-ignored, and requires approval for everything
  else — the same logic every built-in file-editing tool uses.
  (`src/tools/_approval.py` is a leading-underscore "internal" module, same as
  the rest of `src/tools/_*.py` — it's stable enough that built-ins depend on
  it, but treat it as internal API that could change shape, not a frozen
  public contract.)

- `request_unredacted=True` in the incoming args **always** forces approval
  regardless of your `needs_approval` — that check happens before your
  function is even called, so you don't need to handle it.

---

## 9. `dirty_effects` (optional)

```python
def dirty_effects(args: dict, session_data: dict | None = None) -> dict:
    ...
```

- Optional — declares which files/session-memory-keys this call reads or
  writes, feeding the "dirty cache" that blocks stale edits (e.g. writing to
  a file the agent hasn't re-read since it last changed).
- Arity: 1 or 2 params only (no `special_resources` variant).
- Return a dict using any of these keys (all optional, all lists):

  | Key | Meaning |
  |---|---|
  | `dirties_files` | Paths this call writes/mutates. |
  | `cleans_files` | Paths this call fully re-reads (clears their dirty flag). |
  | `requires_clean_files` | Paths that must have been read, and not dirty, before this call is allowed to run. |
  | `dirties_mem` | Session-memory keys this call writes. |
  | `cleans_mem` | Session-memory keys this call fully reads. |
  | `requires_clean_mem` | Session-memory keys that must be clean before this call runs. |

  See `write_text_file.dirty_effects` for the simplest real example
  (`{"dirties_files": [path]}`), and `src/tools/_dirty_cache.py` for the full
  mechanics. If your tool doesn't touch anything another tool would care
  about staleness for, omit `dirty_effects` entirely — that's the majority
  case (read-only, non-file tools).

---

## 10. Redaction opt-in (optional)

By default a tool's return value is **not** passed through the secret
redactor. To opt in:

```python
ENABLE_REDACTION = True            # default False
ALLOW_REQUEST_UNREDACTED = True    # default True; only meaningful if ENABLE_REDACTION=True
```

- `ENABLE_REDACTION = True` runs your tool's return value through
  `src.redaction.core.redact` before it reaches the agent, and — only in this
  case — the framework auto-injects an optional `request_unredacted: boolean`
  parameter into your `DEFINITION` for the LLM to request a bypass (approval
  is then forced regardless of your `needs_approval`, per §8).
- `ALLOW_REQUEST_UNREDACTED = False` keeps redaction on but removes the
  bypass entirely — no `request_unredacted` param is injected, so there's no
  way to see the unredacted output, not even with approval.
- Do **not** add `request_unredacted` to your own `properties` — see §4.

---

## 11. Tool wrapping — delegating with `NextTool`

A tool can wrap/compose another tool (built-in or custom) by returning a
`NextTool` instead of its normal terminal value. This is how you get a
tool that's really "call `basic_web_request` with these specific,
hardcoded-shape arguments" or "call `write_text_file` but reject one of its
parameters" without reimplementing approval, redaction, validation,
truncation, or dirty-tracking yourself — the central dispatcher
(`src/tools/__init__.py`) follows the delegation and applies all of that
exactly as it would for a directly-called tool.

```python
from src.tools import NextTool

def execute(args, session_data, special_resources=None):
    return NextTool("basic_web_request", {"url": build_url(args), "method": "GET"})
```

### 11.1 The three chains

`needs_approval`, `dirty_effects`, and `execute` can each return a
`NextTool(name, args)` instead of their normal terminal value (`bool`,
`dict`, `str`). Whichever hop first returns something else ends that
chain — there's no cap on how many hops other than `MAX_TOOL_DELEGATION_HOPS`
(5, `src/config/tool_execution.py`); exceeding it, or a tool name reappearing
in the same chain (a cycle), is always a hard error — there's no legitimate
use for either, since delegation isn't eagerly evaluated.

A missing function at any hop (not just the first) terminates that chain at
its default: no `needs_approval` → not needed; no `dirty_effects` → `{}`.
Each hop's args are validated against **that hop's own** `DEFINITION` before
its `execute` runs — a wrapper that constructs a malformed delegated call
fails loudly with a schema error, not silently.

### 11.2 Redaction and stubbing: strictest across the whole chain, never loosened

`ENABLE_REDACTION`, `ALLOW_REQUEST_UNREDACTED`, and `NO_STUB` are evaluated
across **every hop the `execute` chain actually visits**, not just the tool
the LLM nominally called:

- If *any* hop sets `ENABLE_REDACTION = True`, the final result is redacted —
  even if your wrapper never declares it itself. This is what makes wrapping
  safe by default: wrap `read_text_file` and you inherit its redaction
  whether you remembered to opt in or not.
- If *any* hop sets `ALLOW_REQUEST_UNREDACTED = False`, the bypass is
  forbidden for the whole call, regardless of what an earlier or later hop
  allows.
- If *any* hop sets `NO_STUB = True`, the result is never stubbed.

None of these ever get *looser* partway through a chain — only stricter.
One consequence worth knowing: whether the LLM can even *see* a
`request_unredacted` parameter on your wrapper is decided when its
`DEFINITION` is built, before any call happens — that can't be inferred from
what you delegate to at runtime. If you want the bypass requestable through
your wrapper, you still have to declare `ENABLE_REDACTION`/
`ALLOW_REQUEST_UNREDACTED` on your own module (§10); if you don't, your
wrapper still redacts safely, it just never offers the bypass.

### 11.3 The divergence check — what keeps a wrapper's approval honest

`needs_approval`, `dirty_effects`, and `execute` are walked as three
independent chains. But whenever more than one of them is *still
delegating* (each has proposed a `NextTool`) and their proposed **tool name
and args don't match exactly**, loading a session doesn't fail — this fails
at call time, loudly, with `ToolDelegationError` naming both chains, the hop
index, and both diverging targets. This is deliberate: it stops a
wrapper whose `needs_approval` claims one thing while its `execute` actually
does another — approving for path A but writing to path B, for example.
Honest wrappers (the ones whose `needs_approval`/`dirty_effects` simply
don't override the default, or delegate with the exact same args `execute`
uses) never hit this.

### 11.4 `extend_tool_definition` — building a wrapper's schema from another's

```python
from src.tools import extend_tool_definition

DEFINITION = extend_tool_definition(
    basic_web_request.DEFINITION,
    {
        "function": {
            "name": "get_quote",
            "description": "...",
            "parameters": {"properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
        },
    },
    remove_keys=["url", "method", "body"],
)
```

Pure — always deep-copies both arguments, never mutates them. This matters:
`original` is very often a shared, module-level `DEFINITION` dict (a
built-in's), reused by every session in the process; a version that mutated
in place would corrupt it permanently, for everyone. `function.name`/
`description` take `new`'s value if given, else `original`'s.
`parameters.properties` is shallow-merged — keys in `new` override/add,
everything else is kept from `original`. `parameters.required`/
`additionalProperties`/`type` take `new`'s value if given (replacing
entirely), else `original`'s. `remove_keys` is applied last, stripped from
both the merged `properties` and the merged `required`.

### 11.5 Worked example: wrapping `basic_web_request` for a stock quote

A `stock_info` skill (`skills/stock_info.md`) with a matching skill-scoped
plugin (`custom_tool_guide.md` §6) that turns the general-purpose
`basic_web_request` into a single-argument `ticker` lookup against a free,
no-key quote endpoint (Yahoo Finance's chart endpoint — illustrative; verify
a real provider's terms/stability before depending on one. This example
originally wrapped Stooq's CSV quote endpoint until it stopped responding —
exactly the kind of drift this caveat is warning about):

```text
skills/
  skills.json               # gives the skill a purpose-written name/blurb
  stock_info.md
tools/
  stock_info/
    __init__.py              # empty — namespace defaults to "stock_info"
    get_quote.py
```

```json
// skills/skills.json
{
  "stock_info": {
    "name": "Stock Quotes",
    "blurb": "Fetch a live stock quote (price, volume, OHLC) for a ticker symbol -- e.g. 'what's AAPL trading at' or 'give me a quote for MSFT'. Not for historical data, charts, or company fundamentals.",
    "dependencies": [],
    "autoload": false
  }
}
```

The `blurb` here matters more than it might look — it's the *only* thing
the per-subturn skill selector sees when deciding whether this skill (and
therefore `stock_info_get_quote`, §6) should be active for a given request;
see `custom_skill_guide.md` §4/§5 for why a specific, boundary-stating blurb
like this one beats the inferred default.

```python
# tools/stock_info/get_quote.py
from src.tools import NextTool, basic_web_request, extend_tool_definition

DEFINITION = extend_tool_definition(
    basic_web_request.DEFINITION,
    {
        "function": {
            "name": "get_quote",
            "description": (
                "Fetch a free stock quote (date/time, open/high/low/close, previous "
                "close, volume) for a ticker symbol via Yahoo Finance's "
                "key-less chart endpoint. Returns raw JSON."
            ),
            "parameters": {
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol, e.g. AAPL.",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    # Drop everything request-shape-specific; keep what's still generically
    # useful (timeout).
    remove_keys=[
        "url", "method", "content_type", "headers", "body",
        "debug_show_bad_json", "load_service_tokens", "target", "memory_key",
    ],
)


def execute(args, session_data, special_resources=None):
    ticker = args["ticker"].strip().upper()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
    return NextTool(
        "basic_web_request",
        {
            "url": url,
            "method": "GET",
            "accept": "application/json",
            "headers": {"User-Agent": "Mozilla/5.0"},
        },
    )
```

No `needs_approval` override needed — `basic_web_request` doesn't define one
today, so both the `needs_approval` and `execute` chains resolve to "no
approval needed" for the same tool with the same args, no divergence risk.
The final tool name is `stock_info_get_quote` (§6's namespace prefix), only
active on subturns where the `stock_info` skill is active (§6).

---

## 12. `special_resources` reference

Passed as the 3rd positional argument to `execute`/`needs_approval` when your
function's signature declares enough parameters to receive it (see §7/§8).
Built by `_execute_tools` in `tool_execution.py`; treat this table as
reflecting that function, not a frozen public API:

| Key | Type | Notes |
|---|---|---|
| `session_id` | `str` | |
| `session_init_working_dir` | `str` | The session's original `--cwd`. Always a valid approved root. |
| `session_current_working_dir` | `str` | Current cwd, tracked across `change_pwd` calls. Prefer this over `session_init_working_dir` for resolving relative paths. |
| `approval_mode` | `str` | Live, re-read before every tool call in a turn — see §8. |
| `create_file_auto_eol` | `str \| None` | Auto-EOL policy for newly-created files (see `src/tools/_auto_eol.py`). |
| `request_unredacted` | `bool` | Resolved bypass decision (only meaningful if `ENABLE_REDACTION=True`); set right before `execute` is called. |
| `on_chunk` | `callable(str) -> None` | Stream progress text (§7). Only present during `execute`, not `needs_approval`. |
| `on_cwd_change` | `callable(str) -> None` | Call this if your tool changes the session's cwd (see `change_pwd.py`). |
| `cancel_event` | `threading.Event \| None` | Set if the user cancels the turn — long-running tools should poll it. |
| `emit_backend_log` | `callable(*msgs) -> None` | Writes to the session's Debug Panel log stream. |
| `llm` | object | The session's configured LLM client, for tools that want to make their own sampling calls (e.g. a summarizer). |
| `create_terminal` / `get_terminal_output` / `get_terminals_state` | callables | Terminal-panel integration — see `open_in_terminal.py`/`check_terminal_state.py` for real usage. |
| `summarizer_params` / `patchrewriter_params` | `dict` | Config passthrough for tools that invoke those subsystems directly. |
| `on_sampler_usage` / `on_sampler_request_log` / `on_sampler_response` / `make_sampler_callbacks` | callables | Cost/usage tracking hooks for any LLM call your tool makes. |

---

## 13. Imports — where your code can pull from

This is the part specific to how the SLBP runtime wires `sys.path`, and it
has **two independent guarantees** plus one manual pattern.

### 12.1 Importing SLBP internals (`from src.xxx import yyy`) — always works

The running `slbp server` process always has the **repository root** on its
`sys.path`, regardless of anything the tool loader does:

- The `slbp`/`slbp.cmd` launcher and `python_in_env.sh` both `export
  PYTHONPATH="$REPO_ROOT:$PYTHONPATH"` before starting Python.
- `src/ui_connector/main.py` also does
  `sys.path.insert(0, <repo root>)` directly as a second, redundant
  guarantee, at process start.

Because your custom tool code executes *inside that same running process*
(the loader `exec`s your file in-process via `importlib.util`, it does not
spawn a subprocess), this means **every custom tool can freely do**:

```python
from src.utils.env_info import get_default_workspace_dir
from src.tools._approval import ApprovalContext, is_full_auto
from src.utils.exceptions import ToolTimeoutError
```

— exactly like a built-in tool does, with no extra setup. This works
regardless of where `tools/` lives, how the session was created, or what
`workspace_root` was passed to the loader.

The caveat is stability, not availability: everything under `src/` is this
project's own implementation, not a published package with a compatibility
contract. Public-looking modules (`src.utils.env_info`, etc.) are reasonably
safe to lean on; leading-underscore modules (`src.tools._approval`, and every
other `src/tools/_*.py`) are internal by convention, even though built-in
tools themselves depend on them. Treat either like depending on another
team's internal module — fine, but expect it to move if the project
refactors.

**Wrapping/composing another tool — not yet a supported pattern.** This
same blanket rule technically lets you `from src.tools.read_text_file import
execute` and call it directly, but doing so bypasses everything
`execute_tool` normally wraps it with — arg schema validation, reserved-
param stripping, redaction (`ENABLE_REDACTION`/`ALLOW_REQUEST_UNREDACTED`
are applied by `execute_tool`, not by `execute()` itself), truncation, and
stubbing. Calling `execute_tool()` itself instead (also exported from
`src.tools`, alongside `_TOOL_MAP`) recovers full framework treatment for
wrapping a *built-in*, but there's currently no clean way to reach another
*custom* tool's full merged map from inside a tool's own `execute()` — it
isn't exposed via `special_resources`. Robust tool-wrapping/composition is
a deliberately deferred feature, not implemented yet — don't build on it.

### 12.2 Importing from your own plugin's location

Unlike `src/`, **your plugin's own directory is not added to `sys.path`
automatically.** The loader only ever adds one directory to `sys.path`:
`workspace_root` (whatever the caller of `load_custom_tools` passed — in
practice, the session's `initial_cwd`, i.e. `--cwd`), and never removes it —
over a long-running server it just accumulates every workspace root ever
seen. Each tool *file* is imported individually via
`importlib.util.spec_from_file_location` under a private, auto-generated
module name — it is never imported as `my_plugin.do_thing`, so a plain
`import do_thing` or `from . import _helpers` from inside a tool file will
**not** find sibling files in the same folder by default.

**Use `import_local` (recommended — the only pattern safe under concurrent
sessions):**

```python
# tools/my_plugin/do_thing.py
from src.tools import import_local

_helpers = import_local("_helpers.py")  # resolved against this file's own directory

DEFINITION = {...}

def execute(args, session_data, special_resources=None):
    return _helpers.format_target(args["target"])
```

`import_local(path)` (`src/tools/__init__.py`) imports a file by path —
absolute, or relative to *your* file (resolved via the caller's `__file__`
through the call stack, so a relative path always means "next to me," not
"next to whoever happens to call this"). `_helpers.py` here has no
`DEFINITION`, so the loader itself still executes it once at plugin-load
time (to satisfy any earlier `import_local` calls) and otherwise ignores it
as a tool — see §3 for the helper-file mechanics that make that safe.

**Why not a bare `import` statement, or manual `sys.path` manipulation?**
`sys.modules` is one flat, process-wide namespace, shared by every thread
and every session in the running server — there is no per-thread or
per-session `sys.path`/`sys.modules` in Python (the "each session gets its
own thread" threading model doesn't extend to imports). Two *different*
plugins that happen to name a helper file the same thing — `_helpers.py` is
a very plausible collision, it's the example used throughout this guide —
would otherwise resolve to whichever one was imported *first*, for every
other session, for the rest of the process's life, silently. `import_local`
sidesteps this entirely: the module name it generates is derived from the
file's own resolved absolute path (hashed), so two different files never
collide regardless of what they're named. Repeated calls for the *same*
path — by the same or a different session — correctly return the same
cached module, same semantics as an ordinary top-level `import`, just with
a collision-safe name driving the cache key. Because that cache is
path-keyed rather than session-keyed, treat an `import_local`-loaded module
like any other shared Python module: fine for stateless helpers (the
overwhelmingly common case), not a place to keep mutable state that must
stay isolated per session.

If you're reading older custom tool code (or examples predating this
guide's current revision) that instead does manual
`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` followed
by a bare `import _helpers`, or a package-style
`from tools.my_plugin import _helpers` relying on `workspace_root` being on
`sys.path` — both still run, but both have exactly the collision problem
above (the package-style form is worse: `tools` itself is a name *every*
session using `--load-custom-skills-tools` shares, so the very first `import tools`
anywhere in the process wins for everyone, permanently). Migrate them to
`import_local` rather than copying the pattern forward.

**Vendoring third-party dependencies:** use `tools/__init__.py` (§1) to
`sys.path.insert` a vendored `site-packages`-style directory once per
session, before any plugin's tool files are imported:

```python
# tools/__init__.py
import os
import sys

_vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
if _vendor not in sys.path:
    sys.path.insert(0, _vendor)
```

---

## 14. Pre-flight checklist

Before wiring a new tool file into a session, confirm:

- [ ] `DEFINITION["type"] == "function"`.
- [ ] `DEFINITION["function"]["name"]` is set (base name — no namespace prefix).
- [ ] `DEFINITION["function"]["description"]` is explicit about preconditions,
      mutually-exclusive args, and when to use this tool vs. an alternative.
- [ ] `DEFINITION["function"]["parameters"]["type"] == "object"`.
- [ ] `properties` covers every arg your `execute` reads from `args`;
      `required` lists the mandatory ones; `additionalProperties: False` set.
- [ ] No property named `request_unredacted`.
- [ ] `execute(args, session_data, special_resources=None)` exists, returns a
      `str` (or a `NextTool` if wrapping — §11) in every code path (including
      error paths — return `"Error: ..."` strings, don't raise for expected
      failure modes).
- [ ] Deliberately chosen: unscoped (root-level, always active) or
      skill-scoped (namespaced plugin folder, active only with its skill —
      see §6).
- [ ] If skill-scoped: the resolved namespace (folder name, or explicit
      `TOOL_NAMESPACE`) matches an existing skill id — built-in or custom.
- [ ] The resulting final tool name doesn't collide with a built-in, an
      unscoped custom tool, or another plugin's tool.
- [ ] `needs_approval` added (or deliberately omitted) for anything that
      writes, deletes, executes, or makes network calls.
- [ ] `dirty_effects` added if this tool reads/writes files or memory keys
      that other tools' staleness-checks should know about.
- [ ] `ENABLE_REDACTION = True` set if output might contain secrets scraped
      from files/commands/network responses.
- [ ] `NO_STUB = True` set only if truncated/stubbed output would break the
      agent's ability to use the result (structured dumps, confirmations that
      must be read in full).
- [ ] Any cross-file import inside a plugin uses `import_local` (§13.2), not
      a bare `import sibling_file` or manual `sys.path` manipulation.
- [ ] If wrapping another tool (§11): `needs_approval`/`dirty_effects` are
      either left as the honest default or delegate with the *exact* same
      target and args `execute` uses — a mismatch is a hard error, by design.

A tool file that satisfies the required items (`DEFINITION`, `execute`, a
skill-scoped plugin's namespace matching a real skill id) will load; the
optional items are what separates "loads without error" from "behaves
correctly" once real users and real approval modes are in play.
