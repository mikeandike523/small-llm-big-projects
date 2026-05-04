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
  pendingOutput: string
}

interface TerminalSessionState {
  terminal_id: string
  name: string
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
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 5px 8px;
  border-bottom: 1px solid #17283c;
  background: #09111c;
  overflow-x: auto;
  flex-shrink: 0;
`

const tabButtonCss = (active: boolean, exited: boolean) => css`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 150px;
  min-width: 0;
  height: 24px;
  padding: 0 7px;
  border-radius: 5px;
  border: 1px solid ${active ? '#477bb0' : '#1e344d'};
  background: ${active ? '#132940' : '#0d1a28'};
  color: ${exited ? '#617286' : active ? '#e3f0ff' : '#9ab3ce'};
  font-family: 'Consolas', monospace;
  font-size: 11px;
  cursor: pointer;
  &:hover { border-color: #5f8fc0; }
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
}: {
  tab: TerminalTabState
  active: boolean
  panelOpen: boolean
  socket: Socket
  updateTab: (terminalId: string, patch: Partial<TerminalTabState>) => void
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
    xterm.open(containerRef.current)
    if (tab.pendingOutput) xterm.write(tab.pendingOutput)

    const dataDisposable = xterm.onData(data => {
      socket.emit('terminal_input', { terminal_id: tab.terminalId, data })
    })
    const resizeDisposable = xterm.onResize(({ cols, rows }) => {
      socket.emit('terminal_resize', { terminal_id: tab.terminalId, rows, cols })
    })

    updateTab(tab.terminalId, { xterm, fitAddon, pendingOutput: '' })
    safeFit(containerRef.current, fitAddon)

    return () => {
      dataDisposable.dispose()
      resizeDisposable.dispose()
      xterm.dispose()
    }
  }, [socket, tab.pendingOutput, tab.terminalId, updateTab])

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
    pendingOutput: '',
  }
}

export function TerminalPanel({ open, onToggle, socket, pwd }: Props) {
  const [tabs, setTabs] = useState<TerminalTabState[]>([])
  const [activeTabIdx, setActiveTabIdx] = useState(0)
  const tabsRef = useRef<TerminalTabState[]>([])

  useEffect(() => {
    tabsRef.current = tabs
  }, [tabs])

  const updateTab = useCallback((terminalId: string, patch: Partial<TerminalTabState>) => {
    setTabs(prev => prev.map(tab => tab.terminalId === terminalId ? { ...tab, ...patch } : tab))
  }, [])

  useEffect(() => {
    function onTerminalOutput({ terminal_id, data }: { terminal_id: string; data: string }) {
      const tab = tabsRef.current.find(t => t.terminalId === terminal_id)
      if (tab?.xterm) {
        tab.xterm.write(data)
      } else if (tab) {
        updateTab(terminal_id, { pendingOutput: tab.pendingOutput + data })
      }
    }

    function onTerminalExited({ terminal_id, exit_code }: { terminal_id: string; exit_code: number | null }) {
      const exitText = `\r\n\x1b[33m[process exited with code ${exit_code ?? '?'}]\x1b[0m\r\n`
      const tab = tabsRef.current.find(t => t.terminalId === terminal_id)
      tab?.xterm?.write(exitText)
      updateTab(terminal_id, {
        exited: true,
        exitCode: exit_code,
        pendingOutput: tab?.xterm ? tab.pendingOutput : (tab?.pendingOutput ?? '') + exitText,
      })
    }

    function onTerminalCreated({ terminal_id, name }: { terminal_id: string; name: string }) {
      setTabs(prev => {
        if (prev.some(tab => tab.terminalId === terminal_id)) return prev
        setActiveTabIdx(prev.length)
        return [...prev, makeTab(terminal_id, name)]
      })
    }

    function onTerminalSessionsState({ sessions }: { sessions: TerminalSessionState[] }) {
      setTabs(prev => {
        const byId = new Map(prev.map(tab => [tab.terminalId, tab]))
        const next = sessions.map(session => {
          const existing = byId.get(session.terminal_id)
          return existing ? { ...existing, name: session.name, exited: false, exitCode: null } : makeTab(session.terminal_id, session.name)
        })
        setActiveTabIdx(idx => Math.min(idx, Math.max(0, next.length - 1)))
        return next
      })
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
    const name = `terminal-${tabsRef.current.length + 1}`
    socket.emit('terminal_create', { name, cwd: pwd || undefined })
  }, [pwd, socket])

  const closeTerminal = useCallback((terminalId: string) => {
    const closingIdx = tabsRef.current.findIndex(tab => tab.terminalId === terminalId)
    socket.emit('terminal_close', { terminal_id: terminalId })
    setTabs(prev => prev.filter(tab => tab.terminalId !== terminalId))
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
