# Plan: /terminal Page (Revised)

## Context / decisions (v2)

- **No invisible session.** Terminals are not persisted, so the /terminal page
  connects as a **terminal-only socket connection with no sessionId**. The
  dashboard stays untouched (no hidden-session filter needed). Scrollback
  serialization is future work (noted at the bottom).
- **New terminals start in `~/.slbp/workspace`** (created silently if missing).
- **Spinner** while a terminal creation request is in flight.
- Shell resolution and home-dir detection must not be affected by WSL — see
  "WSL safety" below.

## WSL safety (why this is already safe)

- Home dir: Python `Path.home()` is used (`src/utils/env_info.py` already does
  this). It resolves from `USERPROFILE`/`HOMEDRIVE`+`HOMEPATH` env vars of the
  *native Windows process* — it never shells out to bash, so WSL's `/home/...`
  can never leak in. Do NOT use `expanduser`-in-bash or `os.popen` tricks.
- Shell resolution: `src/terminal/shell_resolver.py` `_find_git_bash()`
  explicitly rejects WSL bash. `TerminalSessionManager.create(cmd=None)` uses
  `resolve_shell()` from that module. We touch none of this.
- Only the **cwd argument** passed to `PtyProcess` needs a new default.

## Changes

### 1. Backend: default cwd helper
- `src/utils/env_info.py`: add
  `get_terminal_default_cwd() -> str`:
  `Path.home() / ".slbp" / "workspace"`, `mkdir(parents=True, exist_ok=True)`
  (swallow errors, fall back to `Path.home()`), return forward-slash string.
  Pure-stdlib, no new deps, no circular import risk (env_info has none).

### 2. Backend: sessionId optional for terminal-only connections
- `src/ui_connector/socket_handler_components/socket_events.py` `handle_connect`:
  allow missing `sessionId` — register the sid under a terminal-only room.
  Implementation: `_state._sid_to_session_id[sid] = None` is NOT used (other
  handlers treat that as "unknown"). Instead add
  `_state._sid_terminal_only_rooms: set[str]` (or simply use the socket's own
  `sid` as the room). Simplest: for terminal-only clients, keep
  `_sid_to_session_id` clean and add `join_room(sid)`; the sid itself is the
  room.
- `socket_events_terminal.py`: introduce one helper, used by all six handlers:
  ```python
  def _terminal_room() -> str | None:
      sid = request.sid
      return _state._sid_to_session_id.get(sid) or sid  # sid only if terminal-only
  ```
  Because a normal session socket joins its session room and never its own sid
  room, `or sid` is unambiguous: for session sockets the mapped session id
  exists in `_sid_to_session_id`, for terminal-only sockets it doesn't.
  - Replace every `session_id = _state._sid_to_session_id.get(sid); if not
    session_id: return` with `_terminal_room()` (drop the early return —
    terminal-only clients now proceed).
  - `_next_human_terminal_name`, `_get_terminal_meta`, `_terminal_belongs_to_session`,
    output pump etc. keep working unchanged — they just key on the room string
    (sid) instead of a session id. No DB/session-store touchpoints exist in
    these paths, which is exactly why this works without an invisible session.
- `handle_terminal_create`: cwd fallback becomes
  `cwd = _state._session_current_cwd.get(room) or get_terminal_default_cwd()`.
- `_launch_terminal_for_session` (agent-opened, session-scoped): also switch its
  fallback from `os.getcwd()` to `get_terminal_default_cwd()` for consistency.
- **Cleanup on disconnect** (`handle_disconnect` in socket_events.py — confirm
  exact name): for terminal-only sids, destroy all terminals whose room == sid
  and clear their output threads. Terminals belonging to real sessions are
  untouched. Note: this means refreshing /terminal closes its terminals —
  accepted for now (no persistence), same lifetimes as before for /session.

### 3. Frontend: socket without sessionId
- `ui/src/socket.ts` `createSocket(sessionId?)`: make sessionId optional; only
  include the `query` when provided.
- New `ui/src/components/TerminalPage.tsx`:
  - Route: `/terminal` (`App.tsx`: `<Route path="/terminal" .../>`).
  - Top bar: home ⌂ button (top-left, same style/behavior as the dashboard
    button in Chat's session page) navigating to `/`.
  - Body: `<TerminalPanel variant="page" socket={socket} />`.
  - One socket per page mount, `autoConnect:false`, `.connect()` on mount,
    `.disconnect()` on unmount.

### 4. Frontend: TerminalPanel `variant="page"` mode
- `ui/src/components/TerminalPanel.tsx`: add optional `variant?: "panel" |
  "page"` (default "panel") to `Props`.
  - `variant="page"`: no `PanelDivider`, no side-panel `open`/`onToggle`
    gating (always rendered), full-height container css (new `pageCss` in
    `ui/src/css/TerminalPanel.ts`), header row replaced by nothing (page has
    its own top bar with home button), and the "Ask about this terminal"
    footer + ask-modal are hidden (LLM-coupled; revisit later if desired).
  - Tab bar, tooltips, terminal tabs, output buffering, resize handling:
    unchanged.
  - `panelTransitioningRef`/`onTerminalOpenPanel` polling logic is a no-op in
    page mode (`openRef.current` always true).
- Spinner: add `creating: boolean` local state.
  - `createTerminal()` emits `terminal_create` and sets `creating=true`;
    cleared when `terminal_created` arrives (or on error event / 10s timeout
    fallback so it can't get stuck).
  - Spinner rendered over the tab bar / empty state while `creating`.
  - Auto-create on mount in page mode: emit `terminal_create` once on first
    `socket.on("connect")` (with spinner until created). In panel mode,
    behavior is unchanged.

### 5. Frontend: dashboard link
- `ui/src/components/Dashboard.tsx`: add a "Terminal" link next to the existing
  "Config" link → `navigate("/terminal")` (no sessionId needed).

### 6. Desktop app
- The dashboard's SPA navigation already persists per-tab URLs (same mechanism
  as /session), so the link works inside desktop tabs as-is.
- Optional follow-up (not in this change): a dedicated desktop tab kind that
  opens `/terminal` directly.

## Not in scope
- Scrollback serialization / terminal persistence (future: serialize xterm
  buffer + `TerminalSession.read_lines` snapshot to disk per session).
- The "Ask about this terminal" flow on /terminal.

## Open questions
1. Confirm `handle_disconnect` name/location in `socket_events.py` (I know
   disconnect cleanup exists; will wire the terminal-only cleanup there).
2. OK to hide the ask-modal entirely on /terminal (it needs an agent session to
   make sense)?

## Test checklist
- Web: /terminal loads, spinner shows, new shell lands in `~/.slbp/workspace`
  (Windows: `C:\Users\<user>\.slbp\workspace`), runs commands, resize, multiple
  tabs, close tab, refresh → terminals gone (no dashboard entry ever created).
- Web: /session terminal panel unchanged (panel mode untouched paths).
- Backend: session terminals still scoped to session room; terminal-only sid
  terminals destroyed on disconnect.
- Desktop: dashboard → Terminal link opens in-tab and URL persists.
