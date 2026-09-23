# Custom Skill Guide

How to write custom skill guides for `slbp`, what the loader requires for a
skill to be *compliant* (loads without error) and *complete* (actually
reaches the model at the right time), and how skill content gets injected
into a running turn.

This guide describes the loading/selection scheme as implemented in
`src/logic/system_prompt.py` (`build_skill_registry` and friends) and the
per-turn wiring in `src/ui_connector/socket_handler_components/agent_loop.py`
(`_async_agent_loop`) and `watchdogs.py` (`_select_skills_for_turn`). When in
doubt, those files are the source of truth — this guide organizes what they
already enforce. `tests/test_skill_registry.py` is a good second reference
for exact edge-case behavior.

A **skill** is a markdown guide (instructions/workflow/tips for a specific
kind of task) plus a little metadata (id, display name, one-line blurb,
dependencies, autoload flag). Skills are **session-scoped**, loaded once at
session-creation time (`POST /api/sessions`) from a `skills/` directory —
same lifecycle as custom tools (see `custom_tool_guide.md` if you haven't
read it; the loading conventions, `--cwd`-relative directory, and
all-or-nothing load-failure behavior all mirror the tools subsystem).

**This is now a coupled system with custom tools, not two independent
ones.** A `tools/<skill_id>/` plugin folder ties its tools to this skill's
own activation state — read `./custom_tool_guide.md` alongside this guide;
see §6 here for how the two connect.

---

## 1. Directory layout

```text
<project-cwd>/
  skills/
    skills.json              # optional at every directory level
    local_notes.md            # id: "local_notes"
    python/
      skills.json             # optional; ids here must be "python_*"
      linting.md               # id: "python_linting"
      testing.md                # id: "python_testing"
```

- Enabled per-session via `slbp session new --load-skills --cwd <dir>`, which
  sets `skills_path = <dir>/skills` (`src/cli_routes/session.py`). The raw
  `POST /api/sessions` API accepts an arbitrary `skills_path` string, but the
  CLI always uses this `{cwd}/skills` convention.
- Every `.md` file directly inside a directory is a candidate skill. Unlike
  custom tools (flat plugin folders only), **custom skill directories nest
  recursively** — every subdirectory is walked, to any depth.
- `skills.json` is **optional at every directory level**, including nested
  ones. If a `.md` file has no matching entry, its title/blurb are inferred
  from the markdown content (see §3) and it defaults to `autoload: false`,
  no dependencies.
- Built-in skills (`src/logic/built_in_skills/`) are **not** recursive — only
  the top-level `.md` files there are considered. Nesting is a custom-skills
  feature only.

---

## 2. Skill ids and nested directories

A skill's id is its filename stem, prefixed by every enclosing subdirectory
name (relative to the skills root), joined with `_`:

- `skills/local_notes.md` → id `local_notes`
- `skills/python/linting.md` → id `python_linting`
- `skills/python/advanced/generics.md` → id `python_advanced_generics`

**If a nested directory has its own `skills.json`, its keys must be the full
prefixed id, not the bare filename stem** — `skills/python/skills.json` must
key its entry for `linting.md` as `"python_linting"`, not `"linting"`. This
is the single most common way to get this wrong; `tests/test_skill_registry.py:
test_implicit_manifest_and_subdir_prefixing` is a working example.

Keep ids short, lowercase, and `snake_case`. The per-turn skill selector is
an LLM that must transcribe an id **verbatim** to select it (see §5) — a
long or unusual id is a real risk of selection failure, not just a style nit.

---

## 3. Inferred title/blurb (when `skills.json` doesn't cover a file)

If a `.md` file has no corresponding `skills.json` entry, both `name` and
`blurb` are inferred straight from the file content
(`parse_skill_title`/`parse_skill_blurb` in `system_prompt.py`):

- **Title**: the first non-blank line. If it starts with `#`, the `#`s and
  surrounding whitespace are stripped (`## Skill: Browsing the Web` →
  `Skill: Browsing the Web`). Otherwise the raw line is used (truncated at
  50 chars with `...` if longer).
- **Blurb**: up to the first 3 non-blank lines of body text after the
  heading, space-joined, capped at 240 chars with `...` if longer.

A manifest entry's `name`/`blurb`, when present, **always wins** over the
inferred values — use the manifest to give a cleaner display name/blurb than
your heading naturally produces (the built-in `web_browsing.md` does exactly
this: heading is `## Skill: Browsing the Web`, manifest `name` overrides it
to the cleaner `"Browsing the Web"`).

There is no required internal structure for the markdown body itself (no
frontmatter, no required sections) — the built-in skills follow a loose
`Workflow` / `Tools` / `Tips` heading convention (see
`src/logic/built_in_skills/web_browsing.md`) purely as a readability
convention worth copying, not something the loader checks.

---

## 4. `skills.json` manifest schema

Optional at every directory level. Two accepted top-level shapes — pick one
per file:

```json
{
  "coding": {
    "name": "Writing Code",
    "blurb": "Guidance for reading, editing, and validating code changes.",
    "dependencies": ["web_browsing"],
    "autoload": false
  },
  "web_browsing": {
    "name": "Browsing the Web",
    "blurb": "Guidance for searching the web and reading external pages efficiently.",
    "dependencies": [],
    "autoload": false
  }
}
```

or, equivalently, wrapped under a `"skills"` key:

```json
{ "skills": { "coding": { ... }, "web_browsing": { ... } } }
```

Per-entry fields (all optional — an entry can be `{}`):

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | `string` | inferred title | Display name shown in the LLM selector prompt and the UI's `skills_loaded` toast. |
| `blurb` | `string` | inferred blurb | One-liner shown to the skill-selector LLM — this is what it uses to decide relevance, so make it specific about *when* to use the skill. |
| `dependencies` | `string[]` | `[]` | Other skill ids (custom or built-in) that must load whenever this one does. See §7. |
| `autoload` | `boolean` | `false` | See §5 — changes *when* and *how* this skill reaches the model. |

**Strictness**: if `skills.json` exists in a directory, it must describe
**exactly** the `.md` files in that same directory — every markdown file
needs an entry (even if just `{}`) and every entry needs a matching file.
Any mismatch raises `SkillManifestError` at session-creation time
(`"skills.json at ... does not match the markdown files in ..."`) and blocks
the whole session from being created, same all-or-nothing behavior as a
broken custom tool. This check is per-directory — a mismatch two levels
deep only requires fixing that one nested `skills.json`.

A top-level `excludeBuiltinSkills` key may also appear (see §8) — it is
stripped out before the remaining keys are parsed as skill entries, so it
can coexist with real entries in the same flat-shaped file.

---

## 5. `autoload` — the most important thing to get right

This flag changes not just *whether* a skill is used, but *how content
reaches the model* and *when file edits take effect*:

- **`autoload: true`**: resolved (with its full dependency chain — §7) once,
  at session-creation time, and baked directly into the session's static
  system prompt (`build_system_prompt(autoload_entries=...)`, cached in
  `_state._session_system_prompts[session_id]`). It is present on every
  single turn, for the life of the session, whether or not it's relevant.
  **Editing an autoloaded skill's `.md` file after the session was created
  has no effect on that session** — the content was already read and baked
  in. You need a new session to see the change.
- **`autoload: false`** (default): invisible to the static system prompt.
  Instead it's a *candidate* for a lightweight LLM call
  (`_select_skills_for_turn` in `watchdogs.py`) that runs at the start of
  **every subturn**, given the candidate list's `id`/`name`/`blurb` and the
  current user request, and picks zero or more ids to load for that subturn.
  Selected skills' content is then **read fresh from disk every time**
  (`build_injected_skills_section` calls `_read_skill_content` per call, no
  caching) and injected into that specific LLM call's payload — so editing a
  non-autoloaded skill's file **does** take effect immediately, on the very
  next subturn, with no restart needed.

Use `autoload: true` sparingly — it's flat token cost on every single turn
regardless of relevance. Prefer `false` (the default) and write a specific
enough `blurb` that the selector reliably picks it up when actually needed.
Neither of the built-in skills (`coding`, `web_browsing`) autoloads, by way
of reference.

Autoloaded skills are excluded from the selector's candidate pool
(`get_selector_candidate_entries` filters to `autoload == false`) — there's
no way for the selector to "re-select" something already autoloaded, and no
harm in it trying, since it simply never sees those ids as options.

---

## 6. Tying tools to a skill

A skill can have a matching custom tool plugin: `tools/<skill_id>/` (see
`custom_tool_guide.md` §1–§2). The link is implicit — a plugin folder's
namespace (its folder name, or an explicit `TOOL_NAMESPACE` override) must
equal a real skill id, checked at tool-load time. There's nothing to declare
here in `skills.json` for this; the skill doesn't need to know its tools
exist, only the tool plugin needs to name itself correctly.

Once linked, the plugin's tools become visible to the LLM using **exactly
the same activation signal as this skill's own guidance text** — the same
resolved snapshot (autoloaded skills, this subturn's selector picks, plus
dependency closure) decides both at once, recomputed fresh every subturn:

- A skill with `autoload: true` → its plugin's tools are effectively always
  present too, for the same reason its text always is (§5).
- A skill with `autoload: false` (default) → its plugin's tools appear only
  on subturns where the selector actually picks this skill (or a dependent
  skill pulls it in via §7's closure) — same as its guidance text, and just
  as capable of disappearing again on the next subturn if not re-selected.

This is deliberately non-sticky: a tool that was available two subturns ago
can be gone now if its skill wasn't selected this time. The model is told
about this directly (`== DYNAMIC TOOL LIST ==` in `src/logic/system_prompt.py`)
so it doesn't treat a since-vanished tool's earlier use as an error to dwell
on.

A skill with no matching `tools/` folder is completely normal — most skills
are guidance-only. The reverse (a tool plugin whose namespace matches no
skill id at all) is a hard error at load time — see `custom_tool_guide.md`
§6 for the exact message and the three ways to fix it.

### Worked example: `stock_info`

A skill paired with a tool that **wraps** a built-in
(`custom_tool_guide.md` §11) — `stock_info_get_quote` is really
`basic_web_request` underneath, with a hardcoded URL shape and a single
`ticker` argument instead of the general-purpose request parameters:

```markdown
<!-- skills/stock_info.md -->
## Skill: Stock Quotes

Use `stock_info_get_quote` to fetch a free stock quote (date, time,
open/high/low/close, volume) for a ticker symbol.

### Workflow

1. Call `stock_info_get_quote(ticker="AAPL")` (or whichever ticker).
2. The result is raw CSV text — the first line is a header, the second is
   the data row. Parse it directly; no further tool call is needed for a
   simple quote lookup.

### Tips

- Ticker symbols are case-insensitive.
- This wraps `basic_web_request` against a free, no-key quote endpoint —
  treat a fetch failure as a possible upstream/network issue, not a bug in
  the ticker itself, before assuming the symbol is wrong.
```

```text
tools/
  stock_info/
    __init__.py        # empty — namespace defaults to "stock_info"
    get_quote.py        # DEFINITION via extend_tool_definition + execute -> NextTool
```

The tool side (`extend_tool_definition`, the `execute` implementation that
returns `NextTool("basic_web_request", ...)`) is the full example in
`custom_tool_guide.md` §11.5 — this skill file is what makes
`tools/stock_info/` a valid namespace (§6) and is what the per-subturn
selector actually sees (`id -- name -- blurb`, §5) when deciding whether
`stock_info_get_quote` should be offered for a given request.

---

## 7. Dependencies

`dependencies` is a list of other skill ids — custom or built-in, and can
cross that boundary in either direction (a custom skill may depend on a
built-in id like `"coding"`; nothing stops a built-in skill from naming a
custom id either, though you'd have to edit `src/logic/built_in_skills/` to
add that, which is not really "custom" territory).

Whenever a skill is loaded — by autoload resolution or by the selector —
its full dependency closure loads with it
(`resolve_skill_dependency_closure`, depth-first). Dependencies are ordered
**before** the skill that needs them in the injected `== SKILLS ==` section,
so a dependency's guidance is always visible to the model before the
dependent skill's own text.

- An unknown dependency id raises `SkillManifestError` at load time
  ("references unknown dependencies").
- Dependency cycles do not infinite-loop (visited ids are tracked and never
  revisited) but are not a validated-against error either — avoid them
  deliberately, they add nothing over a flat dependency list once resolved.

---

## 8. `excludeBuiltinSkills` — removing (or replacing) a built-in skill

The **top-level** `skills.json` at the root of your `skills_path` (not a
nested one — only the root is read for this) may declare:

```json
{ "excludeBuiltinSkills": ["web_browsing"] }
```

This removes the named built-in skill(s) from the registry entirely for this
session — the selector never sees them, and nothing can depend on them
(depending on an excluded id will fail as an unknown dependency, same as any
other unknown id). Unknown ids in this list are silently ignored (no error);
a non-list or non-string-list value raises `SkillManifestError`.

**Exclude-then-redefine pattern**: the "can't override a built-in id" check
(§9) runs *after* exclusions are applied, against the already-filtered
built-in registry. That means excluding a built-in skill and then defining
your own custom skill with the *same id* is a supported way to fully replace
a built-in skill's content:

```json
{
  "excludeBuiltinSkills": ["coding"],
  "coding": {
    "name": "Writing Code (house style)",
    "blurb": "Our team's code-editing conventions.",
    "dependencies": [],
    "autoload": false
  }
}
```

---

## 9. Compliance / collision rules

- A custom skill id may not equal an *active* built-in skill id (one you
  haven't excluded) — raises `SkillManifestError`
  ("Custom skills may not override built-in skills").
- Every skill id across the combined registry (built-in + custom, all
  directories) must be unique — a duplicate id anywhere raises
  `SkillManifestError`, naming both conflicting file paths.
- All of the above validation happens once, at session-creation time
  (`build_skill_registry`, called from `POST /api/sessions`). A failure
  aborts the whole session — it never partially loads. `POST /api/sessions`
  returns `400` with the `SkillManifestError` message as
  `"Skill loading failed: ..."`.

---

## 10. How this actually reaches the model (for context, not something you write)

You don't need to touch any of this to author a skill — it's here so you
understand what your `autoload`/`blurb` choices actually control:

1. At session creation, `build_skill_registry(custom_skills_path=skills_path)`
   builds the full registry once; it's cached per-session
   (`_session_skill_registries`), along with the resolved autoload set
   baked into the static system prompt. This now runs **before** custom tool
   loading (`load_custom_tools`), which validates each skill-scoped plugin's
   namespace against this same registry's ids — see §6.
2. At the start of every subturn, `_select_skills_for_turn` sends the
   selector-candidate list's `id -- name -- blurb` lines plus the current
   request (and recent transcript) to a small/cheap model, which returns a
   comma-separated list of ids (or `"none"`).
3. `current_turn.selected_skill_ids` records that subturn's picks (for
   session-event persistence/replay); the resolved dependency closure, minus
   whatever's already autoloaded, is injected as an `== SKILLS ==` block
   into that specific LLM call. The *same* resolved snapshot (autoload
   baseline ∪ this subturn's closure) also drives that subturn's active tool
   set — see `custom_tool_guide.md` §6 — recomputed together,
   `agent_loop.py` calls the tool-set builder right after this step.
4. If anything (autoloaded or selected) loaded for a subturn, a
   `skills_loaded` socket event fires with the display names, surfaced in
   the UI.

There is no tool the model calls to read a skill — skills are always
push-injected, never pulled.

---

## 11. Pre-flight checklist

- [ ] Filename is short, lowercase, `snake_case` — it (plus any subdirectory
      prefix) becomes the id the selector LLM must reproduce verbatim.
- [ ] If `skills.json` exists in a directory, it lists *every* `.md` file in
      that same directory, and only those files — no more, no less.
- [ ] Nested `skills.json` entries use the fully-prefixed id
      (`python_linting`, not `linting`).
- [ ] `blurb` is specific enough that a selector model can tell, from the
      blurb alone plus the user's request, whether this skill applies.
- [ ] `dependencies` lists any other skill id (custom or built-in) whose
      guidance this skill assumes the model has already seen.
- [ ] `autoload` is `false` unless you specifically want this skill's full
      text on *every* turn regardless of relevance — and if `true`, you
      understand that editing the file won't affect already-running
      sessions.
- [ ] The id doesn't collide with an existing built-in or custom skill id
      (or, if intentionally replacing a built-in, it's paired with the
      matching `excludeBuiltinSkills` entry in the root `skills.json`).
- [ ] No dependency references an id that doesn't exist (or that you just
      excluded).
- [ ] If this skill should come with its own tools, a `tools/<this_id>/`
      plugin folder exists with that exact id as its namespace (§6,
      `custom_tool_guide.md` §1–§2) — otherwise it's guidance-only, which is
      the normal case.
