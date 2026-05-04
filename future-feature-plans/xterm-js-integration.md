# xterm.js Terminal Integration Plan

## Overview

Add a collapsible right-side terminal panel to the Chat UI, backed by persistent PTY sessions on the server. The panel supports multiple simultaneous terminal tabs (each is an independent shell process), communicates over the existing Socket.IO connection, and uses xterm.js for rendering.

The backend plumbing (`src/terminal/`) is already implemented and tested (13/13 passing). This document covers everything from that layer outward.

---

## Backend plumbing (already done)

| Module | Purpose |
|---|---|
| `src/terminal/shell_resolver.py` | `resolve_shell() -> list[str]` — platform shell argv (Git Bash on Windows, zsh on macOS, $SHELL/bash on Linux) |
| `src/terminal/pty_process.py` | `PtyProcess` — wraps `pywinpty` (ConPTY) on Windows, `ptyprocess` on Unix; background reader thread drains output into a `queue.Queue[bytes]` |
| `src/terminal/session_manager.py` | `TerminalSessionManager` — thread-safe UUID-keyed registry of live sessions |
| `src/terminal/__init__.py` | Public re-exports |
| `tests/test_terminal.py` | 13 smoke tests (shell resolution, PTY lifecycle, echo, resize, session CRUD) |

New entries in `requirements.txt`:
```
pywinpty; sys_platform == "win32"
ptyprocess; sys_platform != "win32"
pytest-timeout
```

---

## New npm packages

```bash
cd ui && npm install @xterm/xterm @xterm/addon-fit
```

| Package | Purpose |
|---|---|
| `@xterm/xterm` | Core terminal emulator — renders via canvas, interprets VT100/ANSI |
| `@xterm/addon-fit` | Resizes xterm's `cols`/`rows` to fill its DOM container pixel-perfectly |

---

## Socket event protocol

All terminal events share the existing Socket.IO connection (`sessionId` room, same `createSocket` instance in `socket.ts`). No new WebSocket endpoint is needed.

### Frontend → Backend

| Event | Payload | Description |
|---|---|---|
| `terminal_create` | `{ name?: string, cwd?: string }` | Open a new PTY shell session |
| `terminal_input` | `{ terminal_id: string, data: string }` | Raw keystrokes from xterm |
| `terminal_resize` | `{ terminal_id: string, rows: number, cols: number }` | Container resized |
| `terminal_close` | `{ terminal_id: string }` | User closed the tab |

### Backend → Frontend

| Event | Payload | Description |
|---|---|---|
| `terminal_created` | `{ terminal_id: string, name: string }` | Confirms creation |
| `terminal_output` | `{ terminal_id: string, data: string }` | Raw PTY bytes decoded as UTF-8 |
| `terminal_exited` | `{ terminal_id: string, exit_code: number \| null }` | Shell process died |
| `terminal_sessions_state` | `{ sessions: Array<{ terminal_id: string, name: string }> }` | Sent on `resume_session` so reconnecting clients can re-attach |

---

## Backend changes (`src/ui_connector/socket_handlers.py`)

### Module-level additions

```python
from src.terminal import TerminalSessionManager, PtyProcess

_terminal_manager = TerminalSessionManager()
# terminal_id -> output pump thread
_terminal_output_threads: dict[str, threading.Thread] = {}
```

### Output pump thread

One daemon thread per terminal session. Drains `PtyProcess.read()` and emits `terminal_output` events to the session room.

```python
def _terminal_output_pump(session_id: str, terminal_id: str, proc: PtyProcess) -> None:
    while proc.is_alive():
        data = proc.read(timeout=0.05)   # blocks at most 50 ms
        if data:
            socketio.emit(
                "terminal_output",
                {"terminal_id": terminal_id, "data": data.decode("utf-8", errors="replace")},
                room=session_id,
            )
    socketio.emit(
        "terminal_exited",
        {"terminal_id": terminal_id, "exit_code": proc.exit_code},
        room=session_id,
    )
    _terminal_output_threads.pop(terminal_id, None)
```

### New @socketio.on handlers

All four handlers follow the existing pattern: look up `session_id = _sid_to_session_id.get(request.sid)`.

```python
@socketio.on("terminal_create")
def handle_terminal_create(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    name = data.get("name", "terminal")
    cwd = data.get("cwd") or None
    session = _terminal_manager.create(name=name, cwd=cwd, rows=24, cols=80)
    t = threading.Thread(
        target=_terminal_output_pump,
        args=(session_id, session.id, session.process),
        daemon=True,
    )
    _terminal_output_threads[session.id] = t
    t.start()
    socketio.emit("terminal_created", {"terminal_id": session.id, "name": name}, room=session_id)


@socketio.on("terminal_input")
def handle_terminal_input(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    terminal_id = data.get("terminal_id", "")
    raw = data.get("data", "")
    session = _terminal_manager.get(terminal_id)
    if session and session.process.is_alive():
        session.process.write(raw.encode("utf-8", errors="replace"))


@socketio.on("terminal_resize")
def handle_terminal_resize(data: dict):
    terminal_id = data.get("terminal_id", "")
    rows = int(data.get("rows", 24))
    cols = int(data.get("cols", 80))
    session = _terminal_manager.get(terminal_id)
    if session and session.process.is_alive():
        session.process.resize(rows, cols)


@socketio.on("terminal_close")
def handle_terminal_close(data: dict):
    sid = request.sid
    session_id = _sid_to_session_id.get(sid)
    if not session_id:
        return
    terminal_id = data.get("terminal_id", "")
    _terminal_manager.destroy(terminal_id)
```

### Modification to `handle_resume_session`

After the existing replay logic, emit the current terminal session list so the frontend can re-attach xterm instances on reconnect:

```python
sessions = _terminal_manager.list_sessions()
socketio.emit(
    "terminal_sessions_state",
    {"sessions": [{"terminal_id": s.id, "name": s.name} for s in sessions]},
    room=session_id,
)
```

---

## Frontend: `TerminalPanel.tsx`

New file: `ui/src/components/TerminalPanel.tsx`

### State shape

```ts
interface TerminalTabState {
  terminalId: string
  name: string
  xterm: Terminal | null       // null until the tab div is mounted and open() called
  fitAddon: FitAddon | null
  exited: boolean
  exitCode: number | null
}
```

### Key implementation notes

**Always-mounted tab divs.** Each tab's container `<div>` stays mounted (just toggled `display: none` for inactive tabs). This is required because `terminal.open(el)` can only be called once per xterm instance, and the canvas must remain in the DOM.

**xterm initialization** happens in a `useEffect` on each `TerminalTab` component on first mount:

```ts
useEffect(() => {
  if (!containerRef.current || tab.xterm) return
  const xterm = new Terminal({
    theme: { background: '#0d0d0d', foreground: '#e0e0e0', cursor: '#8aa4d8' },
    fontFamily: "'Consolas', 'Courier New', monospace",
    fontSize: 13,
    scrollback: 5000,
  })
  const fitAddon = new FitAddon()
  xterm.loadAddon(fitAddon)
  xterm.open(containerRef.current)
  fitAddon.fit()

  xterm.onData(data => socket.emit('terminal_input', { terminal_id: tab.terminalId, data }))
  xterm.onResize(({ cols, rows }) =>
    socket.emit('terminal_resize', { terminal_id: tab.terminalId, rows, cols })
  )

  updateTab(tab.terminalId, { xterm, fitAddon })
}, [])
```

**ResizeObserver** triggers `fitAddon.fit()` whenever the container div changes size. `fit()` recalculates cols/rows and calls `terminal.resize()`, which fires `onResize`, which emits `terminal_resize` to the backend:

```ts
useEffect(() => {
  if (!containerRef.current || !tab.fitAddon) return
  const obs = new ResizeObserver(() => tab.fitAddon!.fit())
  obs.observe(containerRef.current)
  return () => obs.disconnect()
}, [tab.fitAddon])
```

**Socket listeners** are registered once in `TerminalPanel`'s `useEffect`:

```ts
socket.on('terminal_output', ({ terminal_id, data }) => {
  const tab = tabsRef.current.find(t => t.terminalId === terminal_id)
  tab?.xterm?.write(data)
})

socket.on('terminal_exited', ({ terminal_id, exit_code }) => {
  updateTab(terminal_id, { exited: true, exitCode: exit_code })
  // Write a visible "process exited" message into the terminal itself:
  const tab = tabsRef.current.find(t => t.terminalId === terminal_id)
  tab?.xterm?.write(`\r\n\x1b[33m[process exited with code ${exit_code ?? '?'}]\x1b[0m\r\n`)
})

socket.on('terminal_created', ({ terminal_id, name }) => {
  setTabs(prev => [...prev, { terminalId: terminal_id, name, xterm: null, fitAddon: null, exited: false, exitCode: null }])
  setActiveTabIdx(tabs.length)   // switch to new tab
})

socket.on('terminal_sessions_state', ({ sessions }) => {
  // Restore tab stubs for sessions that survived a reconnect.
  // xterm instances start as null and are created when the tab div mounts.
  setTabs(sessions.map(s => ({
    terminalId: s.terminal_id, name: s.name,
    xterm: null, fitAddon: null, exited: false, exitCode: null,
  })))
})
```

---

## UI layout

### Panel placement

The terminal panel sits on the **right** of the main chat area, mirroring the existing debug panel on the left.

```
┌──────────────────────────────────────────────────────────┐
│ debugPanel (left) │      mainArea       │ terminalPanel  │
│  20% or 28px      │      flex: 1        │ 38% or 28px    │
└──────────────────────────────────────────────────────────┘
```

Updated `appLayoutCss` in `Chat.tsx`:
```ts
const appLayoutCss = css`
  display: flex;
  flex-direction: row;
  height: 100vh;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 15px;
  background: #0f0f0f;
  color: #e0e0e0;
`
```
(unchanged — the new panel is just another flex child)

### Terminal panel CSS (collapsed/expanded)

```ts
const terminalPanelWrapperCss = (open: boolean) => css`
  width: ${open ? '38%' : '28px'};
  min-width: ${open ? '280px' : '28px'};
  max-width: ${open ? '680px' : '28px'};
  transition: width 0.2s ease, min-width 0.2s ease, max-width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  height: 100%;
  border-left: 1px solid #1a2a40;
  background: #080f18;
`
```

### Collapsed state

When `terminalOpen === false`, the 28px strip shows:
- A vertical "TERMINAL" label (rotated text, same style as the debug panel toggle)
- A `▶` expand button
- Optionally: a badge with the active session count

### Expanded state

```
┌─────────────────────────────────────┐
│ [tab1 ×] [tab2 ×] [+ New]          │  ← tab bar
├─────────────────────────────────────┤
│                                     │
│   xterm.js canvas                   │  ← terminal content area (flex: 1)
│   (active tab, fills space)         │
│                                     │
└─────────────────────────────────────┘
```

The xterm canvas fills the available height minus the tab bar. The `ResizeObserver` on the canvas container handles any height changes (panel toggle, window resize).

### Tab bar design

- Each tab: pill/chip with `name` text and `×` close button
- Active tab: highlighted border/background
- `+` button on the right: emits `terminal_create { name: 'terminal-N', cwd: currentPwd }`
- Exited tabs: dim color, `(exited)` suffix

---

## Resize event flow

```
Container div changes size
  (panel open/close, window resize, future: drag-to-resize)
        │
        ▼
ResizeObserver fires on the container div
        │
        ▼
fitAddon.fit()
  — measures container pixel size
  — divides by xterm character cell size
  — calls terminal.resize(newCols, newRows)
        │
        ▼
xterm.onResize({ cols, rows })
        │
        ▼
socket.emit('terminal_resize', { terminal_id, rows, cols })
        │
        ▼
handle_terminal_resize (server)
  session.process.resize(rows, cols)
        │
        ▼
pywinpty: ResizePseudoConsole(rows, cols)
ptyprocess: ioctl(fd, TIOCSWINSZ, ...)
        │
        ▼
Shell receives SIGWINCH → reflows output to new width
```

---

## Files to create / modify

| Action | File |
|---|---|
| Create | `ui/src/components/TerminalPanel.tsx` |
| Modify | `ui/src/components/Chat.tsx` — add `terminalOpen` state, `terminalPanelWrapper` CSS, `<TerminalPanel>` in JSX, pass `socket` + `pwd` props |
| Modify | `src/ui_connector/socket_handlers.py` — add `_terminal_manager` singleton, `_terminal_output_pump`, and 4 new `@socketio.on` handlers; emit `terminal_sessions_state` in `handle_resume_session` |
| Modify | `ui/package.json` — add `@xterm/xterm`, `@xterm/addon-fit` |

---

## Implementation order

1. **Socket handlers** — `terminal_create`, `terminal_input`, `terminal_resize`, `terminal_close`, output pump, resume state. Can be tested manually via browser console before any UI exists.
2. **`TerminalPanel.tsx`** — panel shell, tab bar, collapsed strip, xterm mounting, socket listeners.
3. **Wire into `Chat.tsx`** — add the `terminalPanelWrapper`, `terminalOpen` state, toggle button, pass socket.
4. **Polish** — exited-tab styling, `cwd` defaulting to session's current `pwd`, reconnect re-attach.
