# Change Spec: 2025-02-25

## Overview

This spec covers 9 areas of change. Implement all of them.

---

## 1. Five New Project Memory Tool Files (`src/tools/`)

Each backed by `KVManager` with a `project=` argument. The default project is resolved via a
reserved `session_data` key `"__pinned_project__"` (set by the agentic loop — see §5). If that
key is absent or `None`, fall back to `os.getcwd()`. Values are plain-text strings in the MySQL
`project_memory` table.

### Helper pattern (shared across all five tools)

```python
def _get_project(args: dict, session_data: dict) -> str:
    explicit = args.get("project")
    if explicit:
        return explicit
    pinned = (session_data or {}).get("__pinned_project__")
    if pinned:
        return pinned
    return os.getcwd()
```

### `project_memory_get_variable`

- Args: `key` (required), `project` (optional), `target_session_key` (optional — if set, writes
  the fetched value into `session_data["memory"][target_session_key]` and returns a confirmation
  string instead of returning the value inline), `number_lines` (optional bool)
- LEAVE_OUT: `SHORT`
- TOOL_SHORT_AMOUNT: `500`

### `project_memory_set_variable`

- Args: `key` (required), `project` (optional), `value` (optional string — literal text to
  store), `from_session_key` (optional — reads `session_data["memory"][from_session_key]` as
  the source). Exactly one of `value` / `from_session_key` must be provided (runtime-validated,
  return an error string if neither or both are given).
- LEAVE_OUT: `PARAMS_ONLY`

### `project_memory_list_variables`

- Args: `project` (optional), `prefix` (optional), `limit` (optional int), `offset` (optional int)
- LEAVE_OUT: `KEEP`

### `project_memory_delete_variable`

- Args: `key` (required), `project` (optional)
- LEAVE_OUT: `PARAMS_ONLY`

### `project_memory_search_by_regex`

- Args: `key` (required), `pattern` (required), `project` (optional)
- Mirrors `session_memory_search_by_regex` exactly — line-numbered matches with ANSI bold
  highlighting on matched substrings.
- LEAVE_OUT: `SHORT`
- TOOL_SHORT_AMOUNT: `500`

---

## 2. Register New Tools in `src/tools/__init__.py`

For each of the five new tools:
- Add an import at the top
- Add the `DEFINITION` to `ALL_TOOL_DEFINITIONS`
- Add an entry to `_TOOL_MAP`

---

## 3. Update `src/logic/system_prompt.py`

In the `== Memory — Plain Text Values ==` section, add a note explaining that project memory
tools are intentionally minimal. For detailed text manipulation: load into session memory with
`project_memory_get_variable(target_session_key=...)`, edit using session memory tools, then
save back with `project_memory_set_variable(from_session_key=...)`.

---

## 4. Custom Tool Discovery — Subfolder-per-Plugin (`src/tools/__init__.py`)

Replace the existing flat `tools/` loading block (under `if os.environ.get("SLBP_LOAD_CUSTOM_TOOLS") == "1":`)
with subfolder-based discovery.

### New expected directory structure

```
{initial_cwd}/tools/
    moltbook/
        __init__.py      <- defines TOOL_NAMESPACE = "moltbook"
        some_tool.py     <- has DEFINITION + execute()
        helpers.py       <- shared helpers, no DEFINITION (silently skipped)
    otherplugin/
        __init__.py      <- defines TOOL_NAMESPACE = "otherplugin"
        another_tool.py
```

### New loading logic

1. `_custom_tools_root = os.path.join(os.getcwd(), "tools")`
2. `sys.path.insert(0, os.getcwd())` — so `from tools.moltbook.helpers import ...` resolves.
   (Previously was `os.path.dirname(_custom_tools_dir)` which is the same path; semantics now
   clearer.)
3. If `_custom_tools_root` does not exist or cannot be listed: print error + `sys.exit(1)`.
4. Enumerate subdirectories of `_custom_tools_root` (sorted). For each subdir:
   - Skip if not a directory.
   - Skip if no `__init__.py` present (silently — not an error).
   - Load `__init__.py` → require `TOOL_NAMESPACE` string attribute. If missing: print error +
     `sys.exit(1)`.
   - Enumerate all `.py` files in that subdir except `__init__.py` (sorted).
   - For each `.py` file, load it as a module with internal name
     `_custom_{namespace}_{stem}` (where stem = filename without `.py`).
     - If the loaded module has no `DEFINITION` attribute: **silently skip** (helper module).
     - If it has `DEFINITION` but no `execute`: print error + `sys.exit(1)`.
     - Otherwise: prefix `DEFINITION.function.name` with `{TOOL_NAMESPACE}_`, check for
       collisions in `_TOOL_MAP` (print error + `sys.exit(1)` on collision), then append to
       `ALL_TOOL_DEFINITIONS` and `_TOOL_MAP`.
5. Finding zero subdirectories with `__init__.py` is **not** an error.
6. After loading all plugins, populate module-level:

```python
_custom_tool_plugins: list[dict] = [
    {"name": plugin_name, "count": N, "path": plugin_dir_path_as_str},
    ...
]
```

This list is used by the `get_tools_info` socket handler (§9).

---

## 5. `--pin-project-memory` CLI Option

### `src/cli_routes/ui.py`

Add to `ui run`:

```python
@click.option(
    '--pin-project-memory', default=True, type=bool, show_default=True,
    help='Pin the default project memory scope to the working directory at launch time. '
         'When False, project memory defaults to os.getcwd() at the time of each call.',
)
```

Pass into `flask_env`:

```python
flask_env["SLBP_PIN_PROJECT_MEMORY"] = "1" if pin_project_memory else "0"
```

(Always set it, whether True or False, so the default=True is explicit.)

### `src/ui_connector/socket_handlers.py`

At module-load time (alongside `_env_os`, `_env_shell`):

```python
_initial_cwd: str = os.getcwd()
_pin_project_memory: bool = os.environ.get("SLBP_PIN_PROJECT_MEMORY", "1") != "0"

def _get_default_project() -> str:
    return _initial_cwd if _pin_project_memory else os.getcwd()
```

In the agentic loop, when assembling `session_data` before calling `execute_tool`, inject:

```python
session_data["__pinned_project__"] = _initial_cwd if _pin_project_memory else None
```

(The project memory tools read `session_data["__pinned_project__"]` as their default project.)

---

## 6. "Initial CWD" in Env Context and UI

### `src/utils/env_info.py`

Add optional param `initial_cwd: str | None = None` to `get_env_context()`. When provided and
it differs from `os.getcwd()`, append `, Initial CWD: {initial_cwd}` to the output string.

### `src/ui_connector/socket_handlers.py`

- `handle_get_env_info`: emit `{"os": _env_os, "shell": _env_shell, "initialCwd": _initial_cwd}`
- `handle_user_message`: pass `initial_cwd=_initial_cwd` to `get_env_context()`

### `ui/src/components/Chat.tsx`

Extend `envInfo` state type to include `initialCwd: string`.

### `ui/src/components/DebugPanel.tsx`

- Extend `EnvInfo` interface: add `initialCwd: string`
- In `SystemTab`, add `<InfoRow label="Initial CWD" value={envInfo.initialCwd} />`

---

## 7. Two New Socket Handlers — Project Memory Browser

In `src/ui_connector/socket_handlers.py`, add alongside the session memory handlers:

```python
@socketio.on("get_project_memory_keys")
def handle_get_project_memory_keys():
    project = _get_default_project()
    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn).list_keys(project=project)
    emit("project_memory_keys_update", {"keys": keys})

@socketio.on("get_project_memory_value")
def handle_get_project_memory_value(data: dict):
    key = data.get("key", "")
    project = _get_default_project()
    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)
    if value is not None:
        emit("project_memory_value", {"key": key, "value": value, "found": True})
    else:
        emit("project_memory_value", {"key": key, "value": "", "found": False})
```

---

## 8. Project Memory Widget in `DebugPanel.tsx`

Replace the `Under construction.` placeholder in the `project` tab panel with a `ProjectMemTab`
component that mirrors `SessionMemTab`.

### State (inside `DebugPanel`)

Add alongside existing session memory state:

```ts
const [projectMemKeys, setProjectMemKeys] = useState<string[]>([])
const [projectMemModal, setProjectMemModal] = useState<MemModal | null>(null)
```

### Socket wiring (inside `DebugPanel` useEffect)

Listen for:
- `project_memory_keys_update` → `setProjectMemKeys`
- `project_memory_value` → update `projectMemModal` (same pattern as `memModal`)

### Tab activation

```ts
useEffect(() => {
  if (open && activeTab === 'project') {
    socket.emit('get_project_memory_keys')
  }
}, [open, activeTab])
```

### `ProjectMemTab` component

Identical structure to `SessionMemTab` (toolbar with count + refresh button, key list with View
buttons). Refresh emits `get_project_memory_keys`. View emits `get_project_memory_value`.

### Modal

`projectMemModal` uses the same modal JSX already present for `memModal`. Both modals can
render simultaneously (they are independent state). The modal title should make it clear which
scope is shown (e.g. prefix with `[project]`).

---

## 9. Tools Card in Debug Panel — System Info Tab

### Backend: `src/ui_connector/socket_handlers.py`

At module-load time, capture the count of built-in tools before any custom tools are appended:

```python
_builtin_tool_count: int = len(ALL_TOOL_DEFINITIONS)  # set after imports, before custom loading
```

After custom tool loading (§4), `_custom_tool_plugins` is available in `src/tools/__init__.py`.
Import it in `socket_handlers.py`:

```python
from src.tools import _custom_tool_plugins  # list[dict] | empty list
```

Add handler:

```python
@socketio.on("get_tools_info")
def handle_get_tools_info():
    custom_enabled = os.environ.get("SLBP_LOAD_CUSTOM_TOOLS") == "1"
    emit("tools_info", {
        "totalCount": len(ALL_TOOL_DEFINITIONS),
        "builtinCount": _builtin_tool_count,
        "builtinPath": "src/tools/",
        "customPlugins": _custom_tool_plugins if custom_enabled else None,
    })
```

### Frontend: `Chat.tsx`

Add state:

```ts
interface ToolsInfo {
  totalCount: number
  builtinCount: number
  builtinPath: string
  customPlugins: { name: string; count: number; path: string }[] | null
}
const [toolsInfo, setToolsInfo] = useState<ToolsInfo | null>(null)
```

Emit `get_tools_info` on connect (alongside `get_skills_info`, `get_env_info`, etc.).
Listen for `tools_info` → `setToolsInfo`.
Pass as new prop `toolsInfo={toolsInfo}` to `<DebugPanel>`.

### Frontend: `DebugPanel.tsx`

Add to `Props`:

```ts
toolsInfo: ToolsInfo | null
```

Add `ToolsInfo` interface (same shape as above).

New `ToolsCard` component, modeled after `SkillsCard`:

- Header: `"{totalCount} tool{s} loaded"`
- Scrollable body:
  - First line/row: `{builtinPath} ({builtinCount} built-in)`
  - If `customPlugins` is non-null: one row per plugin showing `{name}/ ({count} tools)` with
    the path beneath it in a smaller/dimmer style
  - Then a divider or gap, followed by all tool names listed as `· tool_name` (taken from
    `ALL_TOOL_DEFINITIONS` on the backend — the names array should be included in the
    `tools_info` payload)

**Adjust `tools_info` payload** to also include:

```python
"names": [d["function"]["name"] for d in ALL_TOOL_DEFINITIONS]
```

Pass this through to the `ToolsInfo` interface as `names: string[]` and render in the card body.

Render `<ToolsCard toolsInfo={toolsInfo} />` in `SystemTab`, after `<SkillsCard>`.

---

## Summary Checklist

- [ ] `src/tools/project_memory_get_variable.py`
- [ ] `src/tools/project_memory_set_variable.py`
- [ ] `src/tools/project_memory_list_variables.py`
- [ ] `src/tools/project_memory_delete_variable.py`
- [ ] `src/tools/project_memory_search_by_regex.py`
- [ ] `src/tools/__init__.py` — register 5 new tools + rewrite custom tool loading (§4) + export `_custom_tool_plugins`
- [ ] `src/logic/system_prompt.py` — add project memory note (§3)
- [ ] `src/cli_routes/ui.py` — add `--pin-project-memory` option (§5)
- [ ] `src/utils/env_info.py` — add `initial_cwd` param to `get_env_context()` (§6)
- [ ] `src/ui_connector/socket_handlers.py` — `_initial_cwd`, `_pin_project_memory`, `_get_default_project()`, inject `__pinned_project__` in agentic loop, update `handle_get_env_info`, update `handle_user_message`, add `get_project_memory_keys` handler, add `get_project_memory_value` handler, add `get_tools_info` handler, import `_builtin_tool_count` / `_custom_tool_plugins` (§5, §6, §7, §9)
- [ ] `ui/src/components/Chat.tsx` — `toolsInfo` state + `initialCwd` in envInfo type + `get_tools_info` emit/listen + pass `toolsInfo` prop (§6, §9)
- [ ] `ui/src/components/DebugPanel.tsx` — `EnvInfo.initialCwd`, `ProjectMemTab`, project memory state/socket wiring, `ToolsCard`, `toolsInfo` prop (§6, §8, §9)
