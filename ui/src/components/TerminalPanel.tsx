/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { type Socket } from 'socket.io-client'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

interface TerminalTabState {
  terminalId: string
  name: string
  xterm: Terminal | null
  fitAddon: FitAddon | null
  exited: boolean
  exitCode: number | null
}

interface TerminalSessionState {
  terminal_id: string
  name: string
  snapshot?: string
}

interface Props {
  open: boolean
  onToggle: () => void
  socket: Socket
  pwd: string
}

const panelCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #080f18;
  border-left: 1px solid #1a2a40;
  overflow: hidden;
`

const collapsedStripCss = css`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  background: #080f18;
`

const collapsedLabelCss = css`
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: 'Consolas', monospace;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: #54708f;
  text-transform: uppercase;
`

const toggleButtonCss = css`
  background: transparent;
  border: none;
  color: #7193b6;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 2px;
  &:hover { color: #b9d3ee; }
`

const badgeCss = css`
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  background: #14263b;
  border: 1px solid #294a70;
  color: #9dbce0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Consolas', monospace;
  font-size: 10px;
`

const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 34px;
  padding: 0 8px;
  background: #0b1521;
  border-bottom: 1px solid #17283c;
  flex-shrink: 0;
`

const titleCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #88a8c8;
`

const tabBarCss = css`
  display: flex;
  align-items: flex-end;
  gap: 4px;
  min-height: 36px;
  padding: 5px 8px 0 8px;
  border-bottom: 1px solid #2a4a6a;
  background: #09111c;
  overflow-x: auto;
  flex-shrink: 0;
`

const tabButtonCss = (active: boolean, exited: boolean) => css`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 160px;
  min-width: 0;
  height: 26px;
  padding: 0 8px;
  border-radius: 4px 4px 0 0;
  border: 1px solid ${active ? '#3d6b99' : '#1e344d'};
  border-bottom-color: ${active ? '#0d0d0d' : '#2a4a6a'};
  background: ${active ? '#0d0d0d' : '#0b1521'};
  color: ${exited ? '#55697a' : active ? '#d8ecff' : '#7fa0bc'};
  font-family: 'Consolas', monospace;
  font-size: 11px;
  cursor: pointer;
  margin-bottom: -1px;
  position: relative;
  z-index: ${active ? 1 : 0};
  &:hover {
    border-color: #4d7ba8;
    border-bottom-color: ${active ? '#0d0d0d' : '#2a4a6a'};
    color: ${exited ? '#55697a' : '#b8d8f4'};
  }
`

const tabNameCss = css`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`

const closeTabCss = css`
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 0;
  opacity: 0.7;
  &:hover { opacity: 1; }
`

const newButtonCss = css`
  height: 24px;
  padding: 0 10px;
  border-radius: 5px;
  border: 1px solid #24415f;
  background: #0c1f32;
  color: #a9c4df;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  &:hover { background: #14304b; border-color: #477bb0; }
`

const terminalsCss = css`
  position: relative;
  flex: 1;
  min-height: 0;
  background: #0d0d0d;
`

const terminalContainerCss = (active: boolean) => css`
  position: absolute;
  inset: 0;
  display: ${active ? 'block' : 'none'};
  padding: 8px;
  box-sizing: border-box;
  overflow: hidden;
  .xterm {
    height: 100%;
  }
`

const emptyCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 0;
  color: #4f647b;
  font-family: 'Consolas', monospace;
  font-size: 12px;
`

function safeFit(container: HTMLDivElement | null, fitAddon: FitAddon | null) {
  if (!container || !fitAddon || container.clientWidth <= 0 || container.clientHeight <= 0) return
  try {
    fitAddon.fit()
  } catch {
    // xterm can briefly have no measurable cell size while the panel is animating.
  }
}

function TerminalTab({
  tab,
  active,
  panelOpen,
  socket,
  updateTab,
  drainBuffer,
}: {
  tab: TerminalTabState
  active: boolean
  panelOpen: boolean
  socket: Socket
  updateTab: (terminalId: string, patch: Partial<TerminalTabState>) => void
  drainBuffer: (terminalId: string) => string
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const openedRef = useRef(false)

  useEffect(() => {
    if (!containerRef.current || openedRef.current) return
    openedRef.current = true

    const xterm = new Terminal({
      theme: { background: '#0d0d0d', foreground: '#e0e0e0', cursor: '#8aa4d8' },
      fontFamily: "'Consolas', 'Courier New', monospace",
      fontSize: 13,
      scrollback: 5000,
    })
    const fitAddon = new FitAddon()
    xterm.loadAddon(fitAddon)

    // Drain buffered output BEFORE open() — xterm queues writes internally and
    // flushes them atomically on open(), so the terminal never shows a blank frame.
    const pending = drainBuffer(tab.terminalId)
    if (pending) xterm.write(pending)

    xterm.open(containerRef.current)
    xterm.focus()

    const dataDisposable = xterm.onData(data => {
      socket.emit('terminal_input', { terminal_id: tab.terminalId, data })
    })
    const resizeDisposable = xterm.onResize(({ cols, rows }) => {
      socket.emit('terminal_resize', { terminal_id: tab.terminalId, rows, cols })
    })

    // updateTab syncs tabsRef synchronously, so output events immediately write
    // to this xterm instance instead of going to the buffer.
    updateTab(tab.terminalId, { xterm, fitAddon })
    requestAnimationFrame(() => safeFit(containerRef.current, fitAddon))

    return () => {
      openedRef.current = false
      dataDisposable.dispose()
      resizeDisposable.dispose()
      // Null out xterm in tabsRef synchronously BEFORE dispose, so that any
      // output arriving during the StrictMode cleanup+remount window goes to
      // the buffer and gets drained by the next effect run.
      updateTab(tab.terminalId, { xterm: null, fitAddon: null })
      xterm.dispose()
    }
  }, [socket, tab.terminalId, updateTab, drainBuffer])

  useEffect(() => {
    if (!panelOpen || !active) return
    safeFit(containerRef.current, tab.fitAddon)
  }, [active, panelOpen, tab.fitAddon])

  useEffect(() => {
    if (!containerRef.current || !tab.fitAddon) return
    const obs = new ResizeObserver(() => {
      if (panelOpen && active) safeFit(containerRef.current, tab.fitAddon)
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [active, panelOpen, tab.fitAddon])

  return <div ref={containerRef} css={terminalContainerCss(active)} />
}

function makeTab(terminalId: string, name: string): TerminalTabState {
  return {
    terminalId,
    name,
    xterm: null,
    fitAddon: null,
    exited: false,
    exitCode: null,
  }
}

export function TerminalPanel({ open, onToggle, socket, pwd }: Props) {
  const [tabs, setTabs] = useState<TerminalTabState[]>([])
  const [activeTabIdx, setActiveTabIdx] = useState(0)
  const tabsRef = useRef<TerminalTabState[]>([])
  // Single output buffer for all terminals: accumulates data from terminal_output
  // events that arrive before the xterm instance is ready to accept writes.
  // Keyed by terminal_id. Lives outside React state so appending never triggers
  // a re-render or causes the init effect to re-run (which was the root bug).
  const outputBufferRef = useRef<Map<string, string>>(new Map())

  // Sync tabsRef immediately (before the async React re-render) so that socket
  // event handlers always read current xterm references without a render cycle gap.
  const updateTab = useCallback((terminalId: string, patch: Partial<TerminalTabState>) => {
    const next = tabsRef.current.map(tab =>
      tab.terminalId === terminalId ? { ...tab, ...patch } : tab
    )
    tabsRef.current = next
    setTabs(next)
  }, [])

  const drainBuffer = useCallback((terminalId: string): string => {
    const data = outputBufferRef.current.get(terminalId) ?? ''
    outputBufferRef.current.delete(terminalId)
    return data
  }, [])

  useEffect(() => {
    function onTerminalOutput({ terminal_id, data }: { terminal_id: string; data: string }) {
      const tab = tabsRef.current.find(t => t.terminalId === terminal_id)
      if (tab?.xterm) {
        tab.xterm.write(data)
      } else {
        // xterm not ready yet (tab unknown or init effect not run) — buffer it.
        outputBufferRef.current.set(terminal_id, (outputBufferRef.current.get(terminal_id) ?? '') + data)
      }
    }

    function onTerminalExited({ terminal_id, exit_code }: { terminal_id: string; exit_code: number | null }) {
      const exitText = `\r\n\x1b[33m[process exited with code ${exit_code ?? '?'}]\x1b[0m\r\n`
      const tab = tabsRef.current.find(t => t.terminalId === terminal_id)
      if (tab?.xterm) {
        tab.xterm.write(exitText)
      } else {
        outputBufferRef.current.set(terminal_id, (outputBufferRef.current.get(terminal_id) ?? '') + exitText)
      }
      updateTab(terminal_id, { exited: true, exitCode: exit_code })
    }

    function onTerminalCreated({ terminal_id, name }: { terminal_id: string; name: string }) {
      // Any output that arrived before terminal_created is already in outputBufferRef
      // (written by onTerminalOutput's else branch), so no separate orphan map needed.
      if (tabsRef.current.some(t => t.terminalId === terminal_id)) return
      const next = [...tabsRef.current, makeTab(terminal_id, name)]
      tabsRef.current = next
      setTabs(next)
      setActiveTabIdx(next.length - 1)
    }

    function onTerminalSessionsState({ sessions }: { sessions: TerminalSessionState[] }) {
      const byId = new Map(tabsRef.current.map(tab => [tab.terminalId, tab]))
      const next = sessions.map(session => {
        const existing = byId.get(session.terminal_id)
        if (existing) return { ...existing, name: session.name, exited: false, exitCode: null }
        if (session.snapshot) outputBufferRef.current.set(session.terminal_id, session.snapshot)
        return makeTab(session.terminal_id, session.name)
      })
      tabsRef.current = next
      setTabs(next)
      setActiveTabIdx(idx => Math.min(idx, Math.max(0, next.length - 1)))
    }

    socket.on('terminal_output', onTerminalOutput)
    socket.on('terminal_exited', onTerminalExited)
    socket.on('terminal_created', onTerminalCreated)
    socket.on('terminal_sessions_state', onTerminalSessionsState)

    return () => {
      socket.off('terminal_output', onTerminalOutput)
      socket.off('terminal_exited', onTerminalExited)
      socket.off('terminal_created', onTerminalCreated)
      socket.off('terminal_sessions_state', onTerminalSessionsState)
    }
  }, [socket, updateTab])

  useEffect(() => {
    if (tabs.length === 0) {
      setActiveTabIdx(0)
      return
    }
    if (activeTabIdx >= tabs.length) setActiveTabIdx(tabs.length - 1)
  }, [activeTabIdx, tabs.length])

  const createTerminal = useCallback(() => {
    socket.emit('terminal_create', { cwd: pwd || undefined })
  }, [pwd, socket])

  const closeTerminal = useCallback((terminalId: string) => {
    const closingIdx = tabsRef.current.findIndex(tab => tab.terminalId === terminalId)
    socket.emit('terminal_close', { terminal_id: terminalId })
    const next = tabsRef.current.filter(tab => tab.terminalId !== terminalId)
    tabsRef.current = next
    setTabs(next)
    outputBufferRef.current.delete(terminalId)
    setActiveTabIdx(idx => {
      if (closingIdx < 0 || idx < closingIdx) return idx
      return Math.max(0, idx - 1)
    })
  }, [socket])

  if (!open) {
    return (
      <div css={collapsedStripCss}>
        <button css={toggleButtonCss} onClick={onToggle} title="Open terminal panel" aria-label="Open terminal panel">&lt;</button>
        <span css={collapsedLabelCss}>Terminal</span>
        {tabs.length > 0 && <span css={badgeCss}>{tabs.length}</span>}
      </div>
    )
  }

  const activeTab = tabs[activeTabIdx]

  return (
    <div css={panelCss}>
      <div css={headerCss}>
        <span css={titleCss}>Terminal</span>
        <button css={toggleButtonCss} onClick={onToggle} title="Close terminal panel" aria-label="Close terminal panel">&gt;</button>
      </div>
      <div css={tabBarCss}>
        {tabs.map((tab, idx) => (
          <button
            key={tab.terminalId}
            css={tabButtonCss(idx === activeTabIdx, tab.exited)}
            onClick={() => setActiveTabIdx(idx)}
            title={`${tab.name}${tab.exited ? ` (exited ${tab.exitCode ?? '?'})` : ''}`}
          >
            <span css={tabNameCss}>{tab.name}{tab.exited ? ' (exited)' : ''}</span>
            <span
              css={closeTabCss}
              role="button"
              aria-label={`Close ${tab.name}`}
              onClick={event => {
                event.stopPropagation()
                closeTerminal(tab.terminalId)
              }}
            >
              x
            </span>
          </button>
        ))}
        <button css={newButtonCss} onClick={createTerminal}>+ New</button>
      </div>
      {activeTab ? (
        <div css={terminalsCss}>
          {tabs.map((tab, idx) => (
            <TerminalTab
              key={tab.terminalId}
              tab={tab}
              active={idx === activeTabIdx}
              panelOpen={open}
              socket={socket}
              updateTab={updateTab}
              drainBuffer={drainBuffer}
            />
          ))}
        </div>
      ) : (
        <div css={emptyCss}>
          <button css={newButtonCss} onClick={createTerminal}>+ New terminal</button>
        </div>
      )}
    </div>
  )
}
