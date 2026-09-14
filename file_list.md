# Step 4 File Sweep — Param Call-Site Conversion

Tracked `.py` files (git-tracked, excluding `ui/*`, `desktop/*`, and anything
gitignored), examined 10 at a time for param-registry call sites (`.get(x, default)`,
`or default`, hardcoded literal fallbacks, direct `kv_store`/`kv.get_value` param
reads) to convert to `get_param_value()` from `src/utils/param_helper.py`.

Legend: `[ ]` not yet examined · `[x]` examined (converted call sites found, or
confirmed none present — see Issues section for anything notable).

## Files

- [x] main.py
- [x] run_tool.py
- [x] scripts/check_py.py
- [x] src/channels/__init__.py
- [x] src/channels/slack/__init__.py
- [x] src/channels/slack/session.py
- [x] src/cli_obj.py
- [x] src/cli_routes/chat.py
- [x] src/cli_routes/dashboard.py
- [x] src/cli_routes/desktop.py
- [x] src/cli_routes/endpoint.py
- [x] src/cli_routes/model.py
- [x] src/cli_routes/param.py
- [x] src/cli_routes/phpmyadmin.py
- [x] src/cli_routes/process_doctor.py
- [x] src/cli_routes/profile.py
- [x] src/cli_routes/server.py
- [x] src/cli_routes/server_task.py
- [x] src/cli_routes/service_token.py
- [x] src/cli_routes/session.py
- [x] src/cli_routes/token/helpers.py
- [x] src/cli_routes/token/list.py
- [x] src/cli_routes/token/remove.py
- [x] src/cli_routes/token/rename.py
- [x] src/cli_routes/token/set.py
- [x] src/cli_routes/token/show.py
- [x] src/cli_routes/token/subroutes.py
- [x] src/cli_routes/token/use.py
- [x] src/cli_routes/token_obj.py
- [x] src/config/text.py
- [x] src/config_routes/__init__.py
- [x] src/config_routes/params.py
- [x] src/config_routes/profiles.py
- [x] src/config_routes/tokens.py
- [x] src/data.py
- [x] src/logic/system_prompt.py
- [x] src/redaction/core.py
- [x] src/redaction/plugins/redaction_plugin_dotenv.py
- [x] src/redaction/types.py
- [x] src/terminal/__init__.py
- [x] src/terminal/pty_process.py
- [x] src/terminal/session_manager.py
- [x] src/terminal/shell_resolver.py
- [x] src/tools/__init__.py
- [x] src/tools/_approval.py
- [x] src/tools/_auto_eol.py
- [x] src/tools/_autoresponse.py
- [x] src/tools/_dirty_cache.py
- [x] src/tools/_eol.py
- [x] src/tools/_exclude_builtin_tools.py
- [x] src/tools/_file_snapshot.py
- [x] src/tools/_indentation.py
- [x] src/tools/_list_dir_utils.py
- [x] src/tools/_managed_process.py
- [x] src/tools/_managed_process_llm_triage.py
- [x] src/tools/_managed_process_shared_defs.py
- [x] src/tools/_memory.py
- [x] src/tools/_patch_rewrite_watchdog.py
- [x] src/tools/_path_utils.py
- [x] src/tools/_subprocess.py
- [x] src/tools/_text_editor_actions.py
- [x] src/tools/_text_editor_utils.py
- [x] src/tools/_validate_timeout.py
- [x] src/tools/basic_web_request.py
- [x] src/tools/brave_web_search.py
- [x] src/tools/change_pwd.py
- [x] src/tools/check_terminal_state.py
- [x] src/tools/code_interpreter.py
- [x] src/tools/config.py
- [x] src/tools/copy_dir.py
- [x] src/tools/copy_file.py
- [x] src/tools/create_dir.py
- [x] src/tools/create_text_file.py
- [x] src/tools/delete_file.py
- [x] src/tools/dom_analyzer.py
- [x] src/tools/find_files_by_name.py
- [x] src/tools/get_environment_info.py
- [x] src/tools/get_global_workspace_dir.py
- [x] src/tools/get_pwd.py
- [x] src/tools/host_check_command.py
- [x] src/tools/host_shell.py
- [x] src/tools/line_reader.py
- [x] src/tools/list_dir.py
- [x] src/tools/list_working_tree.py
- [x] src/tools/move_dir_or_file.py
- [x] src/tools/open_in_terminal.py
- [x] src/tools/read_open_terminal.py
- [x] src/tools/read_text_file.py
- [x] src/tools/remove_dir.py
- [x] src/tools/report_impossible.py
- [x] src/tools/restore_file.py
- [x] src/tools/scrape_web_page.py
- [x] src/tools/search_filesystem_by_regex.py
- [x] src/tools/session_memory.py
- [x] src/tools/snapshot_file.py
- [x] src/tools/summarize_memory_item.py
- [x] src/tools/text_editor.py
- [x] src/tools/todo_list.py
- [x] src/tools/wikipedia.py
- [x] src/tools/write_text_file.py
- [x] src/ui_connector/__init__.py
- [x] src/ui_connector/app.py
- [x] src/ui_connector/main.py
- [x] src/ui_connector/socket_handler_components/__init__.py
- [x] src/ui_connector/socket_handler_components/_session_event_emit.py
- [x] src/ui_connector/socket_handler_components/agent_loop.py
- [x] src/ui_connector/socket_handler_components/approval.py
- [x] src/ui_connector/socket_handler_components/emit.py
- [x] src/ui_connector/socket_handler_components/http_api.py
- [x] src/ui_connector/socket_handler_components/llm.py
- [x] src/ui_connector/socket_handler_components/session_store.py
- [x] src/ui_connector/socket_handler_components/socket_events.py
- [x] src/ui_connector/socket_handler_components/socket_events_info.py
- [x] src/ui_connector/socket_handler_components/socket_events_terminal.py
- [x] src/ui_connector/socket_handler_components/socket_events_turn.py
- [x] src/ui_connector/socket_handler_components/state.py
- [x] src/ui_connector/socket_handler_components/terminal.py
- [x] src/ui_connector/socket_handler_components/tool_execution.py
- [x] src/ui_connector/socket_handler_components/tool_preview.py
- [x] src/ui_connector/socket_handler_components/watchdogs.py
- [x] src/ui_connector/socket_handlers.py
- [x] src/utils/app_launcher.py
- [x] src/utils/approval_modes.py
- [x] src/utils/cli/multiline_prompt.py
- [x] src/utils/cli/slash_commands.py
- [x] src/utils/context_errors.py
- [x] src/utils/docker_compose.py
- [x] src/utils/env_info.py
- [x] src/utils/event_log.py
- [x] src/utils/exceptions.py
- [x] src/utils/free_port.py
- [x] src/utils/git_heuristic_is_binary.py
- [x] src/utils/http/__init__.py
- [x] src/utils/http/helpers.py
- [x] src/utils/llm/dialect.py
- [x] src/utils/llm/dialect_openai_family.py
- [x] src/utils/llm/dialect_openai_responses.py
- [x] src/utils/llm/factory.py
- [x] src/utils/llm/openai_model_dialects.py
- [x] src/utils/llm/streaming.py
- [x] src/utils/llm/types.py
- [x] src/utils/param_registry.py
- [ ] src/utils/process.py
- [ ] src/utils/process_doctor.py
- [ ] src/utils/profile_utils.py
- [ ] src/utils/redis_dict.py
- [ ] src/utils/request_error_formatting.py
- [ ] src/utils/scheduled_task.py
- [ ] src/utils/server_state.py
- [ ] src/utils/session_events.py
- [ ] src/utils/session_model.py
- [ ] src/utils/session_schema_repair.py
- [ ] src/utils/sql/kv_manager.py
- [ ] src/utils/sql/session_store_db.py
- [ ] src/utils/text/line_numbers.py
- [ ] src/utils/text_truncation.py
- [ ] src/utils/tool_calling/arguments.py
- [ ] src/utils/tool_calling/strict_mode.py
- [ ] tests/test_approval_modes_policy.py
- [ ] tests/test_llm_dialects.py
- [ ] tests/test_llm_payload_context_retries.py
- [ ] tests/test_run_tool_cli.py
- [ ] tests/test_skill_registry.py
- [ ] tests/test_terminal.py
- [ ] tests/test_tool_approval_hooks.py
- [ ] tests/test_tool_output_truncation.py
- [ ] tool_tests/_view_server.py
- [ ] tool_tests/helpers/__init__.py
- [ ] tool_tests/helpers/_server_script.py
- [ ] tool_tests/helpers/env.py
- [ ] tool_tests/helpers/http_server.py
- [ ] tool_tests/helpers/result.py
- [ ] tool_tests/individual/read_text_file/checks_return_value.py
- [ ] tool_tests/individual/read_text_file/checks_session_memory.py
- [ ] tool_tests/individual/session_memory/checks_append.py
- [ ] tool_tests/individual/session_memory/checks_concat.py
- [ ] tool_tests/individual/session_memory/checks_copy.py
- [ ] tool_tests/individual/session_memory/checks_delete.py
- [ ] tool_tests/individual/session_memory/checks_extract_json.py
- [ ] tool_tests/individual/session_memory/checks_get.py
- [ ] tool_tests/individual/session_memory/checks_list.py
- [ ] tool_tests/individual/session_memory/checks_rename.py
- [ ] tool_tests/individual/session_memory/checks_search_by_regex.py
- [ ] tool_tests/individual/session_memory/checks_set.py
- [ ] tool_tests/individual/test_basic_web_request.py
- [ ] tool_tests/individual/test_brave_web_search.py
- [ ] tool_tests/individual/test_change_pwd.py
- [ ] tool_tests/individual/test_code_interpreter.py
- [ ] tool_tests/individual/test_create_dir.py
- [ ] tool_tests/individual/test_create_text_file.py
- [ ] tool_tests/individual/test_delete_file.py
- [ ] tool_tests/individual/test_get_pwd.py
- [ ] tool_tests/individual/test_list_dir.py
- [ ] tool_tests/individual/test_list_working_tree.py
- [ ] tool_tests/individual/test_remove_dir.py
- [ ] tool_tests/individual/test_report_impossible.py
- [ ] tool_tests/individual/test_scrape_web_page.py
- [ ] tool_tests/individual/test_search_filesystem_by_regex.py
- [ ] tool_tests/individual/test_wikipedia.py
- [ ] tool_tests/individual/text_editor/checks_apply_patch.py
- [ ] tool_tests/individual/text_editor/checks_check_eol.py
- [ ] tool_tests/individual/text_editor/checks_check_indentation.py
- [ ] tool_tests/individual/text_editor/checks_convert_indentation.py
- [ ] tool_tests/individual/text_editor/checks_count_lines.py
- [ ] tool_tests/individual/text_editor/checks_errors.py
- [ ] tool_tests/individual/text_editor/checks_filepath_mode.py
- [ ] tool_tests/individual/text_editor/checks_normalize_eol.py
- [ ] tool_tests/individual/text_editor/checks_read_lines.py
- [ ] tool_tests/individual/text_editor/checks_search_by_regex.py
- [ ] tool_tests/individual/todo_list/checks_01_list_empty.py
- [ ] tool_tests/individual/todo_list/checks_02_add_item.py
- [ ] tool_tests/individual/todo_list/checks_03_list_nonempty.py
- [ ] tool_tests/individual/todo_list/checks_04_get_item.py
- [ ] tool_tests/individual/todo_list/checks_05_update_item.py
- [ ] tool_tests/individual/todo_list/checks_06_close_reopen.py
- [ ] tool_tests/individual/todo_list/checks_07_delete_leaf.py
- [ ] tool_tests/individual/todo_list/checks_08_add_order.py
- [ ] tool_tests/individual/todo_list/checks_09_add_many.py
- [ ] tool_tests/individual/todo_list/checks_10_promotion.py
- [ ] tool_tests/individual/todo_list/checks_11_subtree.py
- [ ] tool_tests/individual/todo_list/checks_12_close_promoted.py
- [ ] tool_tests/individual/todo_list/checks_13_derived_status.py
- [ ] tool_tests/individual/todo_list/checks_14_all_done.py
- [ ] tool_tests/individual/todo_list/checks_15_delete_children.py
- [ ] tool_tests/individual/todo_list/checks_16_deeply_nested.py
- [ ] tool_tests/individual/todo_list/checks_17_auto_strip.py
- [ ] tool_tests/individual/todo_list/checks_18_errors.py
- [ ] tool_tests/individual/todo_list/checks_19_demotion.py
- [ ] tool_tests/individual/todo_list/checks_20_delete_many.py
- [ ] tool_tests/individual/todo_list/checks_21_structure_reminder.py
- [ ] tool_tests/individual/write_text_file/checks_raw_content.py
- [ ] tool_tests/individual/write_text_file/checks_session_memory.py
- [ ] tool_tests/run.py

## Issues

- **`src/channels/slack/__init__.py`** — `_is_slack_enabled()` was reading
  `system.channels.slack.enabled` directly via `KVManager.get_value(key,
  default=False)` (bypassing the registry). Converted to `get_param_value()`.
  No other param call sites found in this batch of 10 (main.py, run_tool.py,
  scripts/check_py.py, src/channels/__init__.py, src/channels/slack/session.py,
  src/cli_obj.py, src/cli_routes/{chat,dashboard,desktop}.py are all
  param-registry-free).

**Batch 2 (11-20):**
- **`src/cli_routes/server.py`** — `_maybe_clear_desktop_log()` had
  `kv.get_value(key, default=False)` duplicating the registry default for
  `desktop.slbp-process.clear-logs-on-start`. Converted to `get_param_value()`.
- **`src/cli_routes/session.py`** — `session_new` had
  `val = kv.get_value(f"{prefix}params.model.irat"); ... val if val is not None
  else False`, duplicating `model.irat`'s registry default. Converted to
  `get_param_value(kv, "model.irat", profile_prefix=prefix)`.
- `src/cli_routes/param.py` and `src/cli_routes/profile.py` both read
  `kv.get_value(key)` for params, but only for keys already known to exist
  (`list`/`show`/`manual` filter to keys present in the DB before reading) —
  no default-fallback logic to unify, so left as-is. `param.py` is also the
  registry's own CLI surface (`slbp param set/unset/list/manual`); its
  validation already goes through `parse_param_value`/`REGISTRY` directly,
  which is correct for a *writer* (get_param_value is for readers).
- `endpoint.py`, `model.py` (reads a plain `model` key, not a registered
  param), `phpmyadmin.py`, `process_doctor.py`, `server_task.py`,
  `service_token.py`: no param-registry call sites.

**Batch 3 (21-30):** all of `src/cli_routes/token/*`, `token_obj.py`,
`config/text.py` — no param-registry call sites (these deal with the separate
`tokens`/`active_token`/`known_providers` tables).

**Batch 4 (31-40):** no conversions.
- `src/config_routes/params.py` (`/api/params` GET/set/unset) and
  `src/config_routes/profiles.py` (`/api/profiles/config`,
  `/api/profiles/<name>/params/<name>` PUT/DELETE) both intentionally read
  only *set* param keys (pre-filtered via `kv.list_keys()` against
  `ALLOWED_PARAMS`/`GLOBAL_PARAMS` before calling `kv.get_value(key)`) — they
  need to distinguish "explicitly set" from "using the default" for the
  editor UI, which `get_param_value()` would collapse by design. Left as-is;
  their writer paths (`set`/`unset`/PUT/DELETE) already go through
  `parse_param_value`/`REGISTRY` correctly.
  - Noted in passing (not touched, out of scope): `params.py`'s
    `_SYSTEM_KEYS`/`_MODEL_EXTRA` tuples (lines 18-25) are still dead code,
    as already recorded in project memory.
- `src/config_routes/tokens.py`, `src/data.py`, `src/logic/system_prompt.py`,
  `src/redaction/*`, `src/terminal/__init__.py`: no param-registry call
  sites at all.

**Batch 5 (41-50):** no conversions. `src/terminal/*`, `src/tools/__init__.py`
(tool loading/dispatch), `_approval.py` (uses `special_resources["approval_mode"]`,
a session-level setting unrelated to param_registry), `_auto_eol.py` and
`_dirty_cache.py` (both take their `mode`/`strict` behavior as a plain function
argument supplied by the caller — the actual param reads live at the call sites
already converted in `socket_events_turn.py`/`tool_execution.py`, tracked
below), `_autoresponse.py`, `_eol.py`, `_exclude_builtin_tools.py`: none read
from the param registry directly.

**Batch 6 (51-60):** no conversions.
- `src/tools/_managed_process_llm_triage.py` reads `watchdog_params` from
  `load_llm_config()`'s returned dict (`_llm_cfg.get("watchdog_params") or
  {}`) rather than calling a single param getter — this is the same
  `factory.py` namespace-dict structural question already flagged at the
  bottom of this file (needs a design decision, not a mechanical swap).
- `src/tools/_patch_rewrite_watchdog.py`'s `patchrewriter_params` and
  `src/tools/_dirty_cache.py`'s `strict` (batch 5) are both plain function
  arguments threaded down from a caller that already reads the param — no
  DB access happens in these files themselves.
- `_file_snapshot.py`, `_indentation.py`, `_list_dir_utils.py`,
  `_managed_process.py`, `_managed_process_shared_defs.py`, `_memory.py`,
  `_path_utils.py`, `_subprocess.py`: no param-registry involvement at all.

**Batch 7 (61-70):** no conversions. All of `_text_editor_actions.py`,
`_text_editor_utils.py`, `_validate_timeout.py`, `basic_web_request.py`,
`brave_web_search.py`, `change_pwd.py`, `check_terminal_state.py`,
`code_interpreter.py`, `config.py`, `copy_dir.py` — the `DEFAULT_*` constants
here (e.g. `basic_web_request.DEFAULT_TIMEOUT`, `brave_web_search.DEFAULT_COUNT`)
are per-tool-call JSON-schema argument defaults (what the LLM's tool call gets
if it omits an argument), a completely separate concept from the DB-backed
system param registry. None of these files touch `param_registry`/`KVManager`.

**Batch 8 (71-80):** no conversions. `copy_file.py`, `create_dir.py`,
`delete_file.py`, `dom_analyzer.py`, `find_files_by_name.py`,
`get_environment_info.py`, `get_global_workspace_dir.py`, `get_pwd.py`,
`host_check_command.py` — none touch param_registry. `create_text_file.py`
reads `sr.get("create_file_auto_eol")` from `special_resources`, i.e. the
value already resolved upstream (the converted call sites in
`socket_events_turn.py`/`socket_events.py`) — not a fresh DB read, so nothing
to convert here.

**Batch 9 (81-90):** no conversions. `host_shell.py`, `line_reader.py`,
`list_dir.py`, `list_working_tree.py`, `move_dir_or_file.py`,
`open_in_terminal.py`, `read_open_terminal.py`, `read_text_file.py`,
`remove_dir.py`, `report_impossible.py` — all tool-argument defaults
(`DEFAULT_TIMEOUT`, `args.get("x", default)` for per-call JSON schema fields)
and `special_resources` consumers; none read from `param_registry`/`KVManager`.

**Batch 10 (91-100):** no conversions. `restore_file.py`, `scrape_web_page.py`,
`search_filesystem_by_regex.py`, `session_memory.py`, `snapshot_file.py`,
`text_editor.py`, `todo_list.py`, `wikipedia.py`, `write_text_file.py` — no
param-registry involvement. `summarize_memory_item.py` reads
`summarizer_params` out of `special_resources` (pre-resolved by the caller) —
same pattern as `_managed_process_llm_triage.py`'s `watchdog_params`, tied to
the `factory.py` namespace-dict discussion below rather than a fresh DB call.

**Batch 11 (101-110):**
- **`src/ui_connector/socket_handler_components/emit.py`** —
  `_get_known_max_context()` built its own storage key via
  `param_storage_key(...)` and called `kv_manager.get_value(kv_key)` raw (no
  registry default, manual `int(...)`/`ValueError` coercion duplicating what
  `ParamSpec.parse_value` already does). Converted to
  `get_param_value(kv_manager, "model.known_max_context", profile_prefix=...)`,
  which also removed the now-redundant manual int coercion (validation already
  happened inside the getter). The `<= 0 -> None` normalization is real
  business logic (not a default-fallback), kept as-is.
- **`src/ui_connector/socket_handler_components/http_api.py`** —
  `api_session_defaults()` reads `_state._SESSION_DEFAULTS_FROM_DB` (currently
  just `model.irat`) via a raw `kv.get_value(prefix + param_key)`, only
  overriding a separately-maintained hardcoded UI default when set. Flagged
  but NOT converted yet — need to check `state.py`'s hardcoded default against
  the registry default first (next batch) before deciding whether to
  fold this into `get_param_value` too.
- `agent_loop.py`, `approval.py`, `llm.py` — all consume already-resolved
  values passed in as function params (`strict_dirty`, `watchdog_params`,
  etc., or `_get_known_max_context()`'s return value) rather than reading the
  DB directly; no new call sites here beyond the one in `emit.py`.
- `__init__.py` (empty), `app.py`, `main.py` (already touched in step 1),
  `socket_handler_components/__init__.py` (empty), `_session_event_emit.py`:
  no param-registry involvement.

**Batch 12 (111-120) — the core fix motivating this whole effort:**
- **`src/utils/llm/factory.py`** — `load_llm_config()`'s "system-only flags"
  block used to build `system_params` by copying whatever profile-scoped
  `system.*` keys happened to exist in the DB, with no defaults applied at
  all (unset keys were simply absent from the dict). Rewrote it to iterate
  `REGISTRY` for every profile-scoped `system.*` entry (plus `model.irat`)
  and resolve each through `get_param_value()`, so `system_params` now
  **always** contains every one of these keys with its registry default
  already applied. This is the single choke point both duplicated call
  sites below fan out from.
- **`src/ui_connector/socket_handler_components/socket_events_turn.py`** —
  both `handle_user_message` and `handle_force_continuation` had the exact
  duplicated block:
  `strict_dirty: bool = llm_config["system_params"].get("strict_dirty", True)`
  (plus similar ad hoc fallbacks for `blank_response_retries`,
  `create_file_auto_eol`, `enable_patch_rewriter`). Since `system_params` is
  now always fully populated, simplified both to direct key access
  (`_system_params["strict_dirty"]`, etc.) — **this is the fix**: `strict_dirty`
  now genuinely defaults to `False` everywhere, matching the registry.
- **`src/ui_connector/socket_handler_components/agent_loop.py`** and
  **`tool_execution.py`** — their function-signature defaults
  (`strict_dirty: bool = True`) were the other half of the inconsistency
  flagged in `param_defaults_checklist.md`; changed both to `False`.
- **`src/ui_connector/socket_handler_components/http_api.py`** — resolved
  the deferred question from batch 11: `state.py`'s
  `_SESSION_DEFAULTS_HARDCODED["interim_response_as_thinking"] = False`
  already matched the registry default for `model.irat`, so no
  inconsistency there. Converted `api_session_defaults()`'s raw
  `kv.get_value(prefix + param_key)` to `get_param_value()` anyway, for
  consistency and so it now validates stored data too.
- `session_store.py`, `socket_events.py`, `socket_events_info.py`,
  `socket_events_terminal.py`, `state.py`, `terminal.py`, `tool_preview.py`,
  `watchdogs.py`: no other param-registry call sites. (`socket_events.py`'s
  `_startup_auto_eol` still has one harmless redundant `or "enabled_silent"`
  fallback layer — left alone since it also guards the "no active
  profile/config at all" case that `get_param_value` can't reach.)

**Batch 13 (121-130):** no conversions. `app_launcher.py`,
`approval_modes.py`, `cli/multiline_prompt.py`, `cli/slash_commands.py`,
`context_errors.py`, `docker_compose.py`, `env_info.py`, `event_log.py`,
`exceptions.py`, `free_port.py` — none touch the param registry. (Also
caught `src/ui_connector/socket_handlers.py`, skipped by accident after
batch 12 — pure import coordinator, no param calls.)

**Batch 14:** `git_heuristic_is_binary.py`, `http/__init__.py`,
`http/helpers.py`, `llm/dialect.py`, `llm/dialect_openai_family.py`,
`llm/dialect_openai_responses.py`, `llm/openai_model_dialects.py`,
`llm/streaming.py`, `llm/types.py` — no param-registry call sites (pure
wire-protocol/dialect logic). `llm/factory.py` and `param_registry.py`
checked off here too — both already fully covered by steps 1-3 and the
batch-12 `system_params` rewrite.
