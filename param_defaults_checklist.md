# Parameter Defaults Checklist

Working doc for the param-registry default-value unification effort (see CLAUDE.md /
conversation history — steps 1-4). Steps 1-3 are done; this file is the step 2
deliverable (decided defaults + call-site audit) and doubles as the checklist for
step 4 (converting call sites to the new central getter).

Status legend for the step-4 column: `[ ]` not started, `[x]` done.

## Sampler namespaces (`model`, `watchdog.model`, `summarizer.model`, `patchrewriter.model`)

Same 5 suffixes exist under all four namespaces (20 params total). All five are
**omittable**: `None` means "omit this key from the outgoing request entirely,"
never `null`. This was already the de facto behavior in `factory.py`
(`_build_namespace_params` / the main-model loop only iterate keys that exist in the
DB), so no behavior change here — only the getter needs to encode "None => omit" as
an explicit, named rule instead of an implicit consequence of which keys happen to be
in a dict.

| Param suffix | Type | Registry default | Call-site notes | Step 4 |
|---|---|---|---|---|
| `temperature` | float 0.0-2.0 | `None` | Only ever read via `factory.py` namespace builders; consistent. | [ ] |
| `top_p` | float 0.0-1.0 | `None` | Same. | [ ] |
| `top_k` | integer >=1 | `None` | Same. | [ ] |
| `max_tokens` | integer >=1 | `None` | Extracted separately in `_call_sampler`/`make_llm*` via `sampler_params.get("max_tokens")`; consistent. | [ ] |
| `request_extra_params` | object | `None` | Merged on top of the namespace dict in `_build_namespace_params`/main-model loop; `or {}` used at both sites — consistent, but should route through the getter so "unset" is explicit rather than relying on kv.get_value's absence. | [ ] |

`*.model.name` overrides (`watchdog.model.name`, `summarizer.model.name`,
`patchrewriter.model.name`): string, system_only, default `None`. "Unset: use the
profile's main model" per description — confirmed by `_build_namespace_params`,
which only sets `params["model"]` when the `name` suffix key exists in the DB.
Consistent.

## `model.*` (non-sampler)

| Param | Type | Registry default | Call-site notes | Step 4 |
|---|---|---|---|---|
| `model.irat` | boolean, system_only | `False` | `cli_routes/session.py:96`: `val if val is not None else False`. Only consumer of the raw kv value; consistent, single site. | [x] |
| `model.known_max_context` | integer >=0, system_only | `None` | `emit.py:_get_known_max_context` treats unset/invalid/<=0 as "feature disabled" (returns `None`). Consistent — the `<= 0` normalization is call-site business logic beyond a plain default, keep it there. | [x] |

## `system.*`

| Param | Type | Registry default | Call-site notes | Step 4 |
|---|---|---|---|---|
| `system.return_value_max_chars` | integer >=1 | `None` | `socket_events_turn.py` (both call sites) reads with **no fallback at all** (`llm_config["system_params"].get("return_value_max_chars")`), and `tool_execution.py` explicitly treats `None` as "never stub." No inconsistency — behavior already matches `None` = disabled. | [x] |
| `system.blank_response_retries` | integer >=0 | `0` | `socket_events_turn.py` (both sites): `.get("blank_response_retries") or 0`. `agent_loop.py` param default also `0`. Consistent. Note: `or 0` would also coerce an explicitly-stored `0` or `False`-ish value the same as unset, which happens to be harmless here since 0 IS the default, but is exactly the sloppy pattern step 4 should replace with the real getter. | [x] |
| `system.strict_dirty` | boolean | **`False`** (changed — see below) | **INCONSISTENCY / deliberate change — FIXED.** Every call site hardcoded `True`: `tool_execution.py:65` (param default), `agent_loop.py:65` (param default), `socket_events_turn.py:133` and `:385` (`.get("strict_dirty", True)`). All 4 now source `False` (registry default), via `factory.py`'s `system_params` rewrite + updated signature defaults. | [x] |
| `system.enable_patch_rewriter` | boolean | `False` | `socket_events_turn.py` (both sites): `.get("enable_patch_rewriter", False)`. `tool_execution.py`/`agent_loop.py` param defaults also `False`. Consistent. | [x] |
| `system.override_strict_tool_def` | boolean | `None` | `streaming.py:150`: `self._system_params.get("override_strict_tool_def")`, `None` treated as "run the automatic per-dialect decision." Tri-state by design (`None`/`True`/`False` are all meaningfully different) — must stay omittable, not coerced to a bool default. Now always present (as `None` when unset) in `system_params` thanks to the `factory.py` rewrite; `streaming.py`'s own `.get()` read needed no change. | [x] |
| `system.create_file_auto_eol` | string enum | `"enabled_silent"` | `socket_events_turn.py` (both sites) converted to direct key access. `socket_events.py`'s startup-tool-calls site still has one redundant (but harmless) `or "enabled_silent"` layer — kept as-is since it also guards the "no active profile/config at all" case. `create_text_file.py`/`write_text_file.py` just read the already-resolved value out of `special_resources`, not the raw param. | [x] |
| `system.channels.slack.enabled` | boolean, global | `False` | `channels/slack/__init__.py:92`: `kv.get_value(key, default=False)`. Docstring already states "Defaults to False when the param is not set." Consistent. | [x] |
| `desktop.slbp-process.clear-logs-on-start` | boolean, global | `False` | `cli_routes/server.py:120`: `kv.get_value(key, default=False)`. Consistent. | [x] |

## Summary of inconsistencies found

1. **`system.strict_dirty`** — the only real call-site inconsistency, and it's the one
   that kicked off this whole effort: every call site currently hardcodes `True`,
   but the user wants the *system-wide* default to become `False`. This needs a
   real behavior change at 4 call sites in step 4, not just a mechanical swap to the
   getter.
2. Everything else checked out consistent across call sites — no other stale/duplicated
   default literals were found beyond the general pattern of "each site re-declares
   the same literal instead of asking the registry," which is precisely what the
   step-3 getter + step-4 sweep eliminates.

## Step 3: central getter

Implemented in `src/utils/param_helper.py` — `get_param_value(kv, name, profile_prefix=None)`.
Reads via `KVManager.get_value`, falls back to `REGISTRY[name].default` when unset,
and validates whatever came out of the DB via `ParamSpec.parse_value` — raising
`ValueError("Data in database is not valid according to parameter registry. Please
contact server administrator.")` if a *stored* value fails validation. An unset key
short-circuits straight to the registry default without going through `parse_value`
(the default is already sanity-checked once at import time in `param_registry.py`).

## Step 4 plan (not started)

For each `[ ]` row above, replace the ad hoc `.get(x, literal)` / `... or literal`
at the call site with `get_param_value(kv, "the.param.name", profile_prefix=...)`,
removing the now-redundant literal. `system.strict_dirty` additionally needs its
literal `True` fallbacks changed to reflect the new `False` default (or, better,
removed entirely in favor of the getter, which will already return `False`).
Sites inside `factory.py`'s `load_llm_config`/`_build_namespace_params` need special
attention since they currently build dicts by iterating whatever keys exist in the
DB rather than iterating `REGISTRY` and calling the getter per-param — that's a
slightly bigger structural change, worth discussing before diving in.
