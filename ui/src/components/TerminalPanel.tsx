/** @jsxImportSource @emotion/react */
import { css, keyframes } from '@emotion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { type Socket } from 'socket.io-client'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

interface TerminalTabState {
  terminalId: string
  name: string
  cmdDisplay: string
  xterm: Terminal | null
  fitAddon: FitAddon | null
  exited: boolean
  exitCode: number | null
}

interface TerminalSessionState {
  terminal_id: string
  name: string
  cmd_display?: string
  snapshot?: string
}

interface Props {
  open: boolean
  onToggle: () => void
  socket: Socket
  busy: boolean
}

const panelCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #080f18;
  border-left: 1px solid #1a2a40;
  overflow: hidden;
  position: relative;
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

const tooltipFadeIn = keyframes`
  from { opacity: 0; }
  to   { opacity: 1; }
`

const tooltipFadeOut = keyframes`
  from { opacity: 1; }
  to   { opacity: 0; }
`

const tooltipCss = (visible: boolean) => css`
  position: fixed;
  transform: translate(-50%, calc(-100% - 6px));
  background: #0e1f33;
  border: 1px solid #2a4a6a;
  border-radius: 4px;
  color: #a8c8e8;
  font-family: 'Consolas', monospace;
  font-size: 10px;
  padding: 3px 8px;
  white-space: nowrap;
  pointer-events: none;
  z-index: 9999;
  animation: ${visible ? tooltipFadeIn : tooltipFadeOut} 80ms ease forwards;
`

const footerCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  padding: 0 12px;
  background: #091525;
  border-top: 1px solid #17283c;
  flex-shrink: 0;
`

const askButtonCss = css`
  height: 30px;
  padding: 0 18px;
  border-radius: 6px;
  border: 1px solid #2d5580;
  background: #0f2540;
  color: #8fc6f0;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  cursor: pointer;
  letter-spacing: 0.03em;
  transition: background 80ms, border-color 80ms, color 80ms;
  &:hover {
    background: #163353;
    border-color: #4d86bf;
    color: #c0dff8;
  }
`

const modalBackdropCss = css`
  position: absolute;
  inset: 0;
  background: rgba(4, 10, 20, 0.72);
  z-index: 100;
`

const modalBoxCss = css`
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 101;
  width: min(420px, 90%);
  background: #0b1b2e;
  border: 1px solid #2a4a6a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 0;
  box-shadow: 0 8px 32px rgba(0,0,0,0.6);
`

const modalHeaderRowCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 10px 14px;
  border-bottom: 1px solid #1e3651;
`

const modalTitleCss = css`
  font-family: 'Consolas', monospace;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #88a8c8;
`

const modalCloseXCss = css`
  background: transparent;
  border: none;
  color: #54708f;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  &:hover { color: #b9d3ee; }
`

const modalBodyCss = css`
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
`

const modalTextareaCss = css`
  width: 100%;
  min-height: 80px;
  resize: vertical;
  background: #07111e;
  border: 1px solid #1e3651;
  border-radius: 5px;
  color: #c8dff0;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  padding: 8px 10px;
  box-sizing: border-box;
  outline: none;
  &:focus { border-color: #3d6b99; }
  &::placeholder { color: #3f5a72; }
`

const modalFollowupRowCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
`

const modalFollowupLabelCss = css`
  font-family: 'Consolas', monospace;
  font-size: 10px;
  color: #4f6a82;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-right: 2px;
`

const modalFollowupPillCss = (active: boolean) => css`
  height: 22px;
  padding: 0 10px;
  border-radius: 11px;
  border: 1px solid ${active ? '#3d6b99' : '#1e344d'};
  background: ${active ? '#0f2a48' : 'transparent'};
  color: ${active ? '#a8d0f0' : '#4f6a82'};
  font-family: 'Consolas', monospace;
  font-size: 10px;
  cursor: pointer;
  &:hover { border-color: #4d7ba8; color: #8ab8e0; }
`

const modalActionsRowCss = css`
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 14px 14px 14px;
  border-top: 1px solid #1e3651;
`

const modalCancelBtnCss = css`
  height: 28px;
  padding: 0 14px;
  border-radius: 5px;
  border: 1px solid #1e344d;
  background: transparent;
  color: #6a8aaa;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  cursor: pointer;
  &:hover { border-color: #3d6b99; color: #9dbce0; }
`

const modalSubmitBtnCss = (disabled: boolean) => css`
  height: 28px;
  padding: 0 16px;
  border-radius: 5px;
  border: 1px solid ${disabled ? '#1e344d' : '#2d6fa0'};
  background: ${disabled ? 'transparent' : '#0f2f52'};
  color: ${disabled ? '#3a5570' : '#7fc0f0'};
  font-family: 'Consolas', monospace;
  font-size: 11px;
  cursor: ${disabled ? 'not-allowed' : 'pointer'};
  &:hover { ${disabled ? '' : 'background: #163d68; border-color: #4d86c0; color: #aad8ff;'} }
`

function getScreenOutput(xterm: Terminal | null): string {
  if (!xterm) return ''
  const buf = xterm.buffer.active
  const start = buf.viewportY
  const end = start + xterm.rows - 1
  const lines: string[] = []
  for (let i = start; i <= end; i++) {
    const line = buf.getLine(i)
    if (line) lines.push(line.translateToString().trimEnd())
  }
  while (lines.length > 0 && lines[lines.length - 1] === '') lines.pop()
  return lines.join('\n')
}

function safeFit(container: HTMLDivElement | null, fitAddon: FitAddon | null) {
  if (!container || !fitAddon) return
  try {
    fitAddon.fit()
  } catch {
    // xterm can briefly have no measurable cell size while layout is settling.
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

  // Refs that always hold the latest prop values so rAF and ResizeObserver
  // callbacks never act on stale closures. Initialized from props so they
  // are correct even before the sync effects below have a chance to run.
  const panelOpenRef = useRef(panelOpen)
  const activeRef = useRef(active)
  useEffect(() => { panelOpenRef.current = panelOpen }, [panelOpen])
  useEffect(() => { activeRef.current = active }, [active])

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

    // Defer fit so the layout has settled. Read refs (not closure values) so
    // we never fit a tab that became inactive or whose panel closed before the
    // frame fired — avoiding a fit on a display:none container.
    requestAnimationFrame(() => {
      if (panelOpenRef.current && activeRef.current) safeFit(containerRef.current, fitAddon)
    })

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

  // Fit whenever the tab becomes active or the panel opens. fitAddon in deps
  // so this fires once fitAddon is available after init.
  useEffect(() => {
    if (!panelOpen || !active) return
    safeFit(containerRef.current, tab.fitAddon)
  }, [active, panelOpen, tab.fitAddon])

  // Container resize → refit, but only when this tab is the visible one.
  // ResizeObserver is recreated only when fitAddon changes (via refs for the
  // panelOpen/active guards so we don't recreate on every tab switch).
  useEffect(() => {
    if (!containerRef.current || !tab.fitAddon) return
    const obs = new ResizeObserver(() => {
      if (panelOpenRef.current && activeRef.current) safeFit(containerRef.current, tab.fitAddon)
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [tab.fitAddon])

  return <div ref={containerRef} css={terminalContainerCss(active)} />
}

function makeTab(terminalId: string, name: string, cmdDisplay: string): TerminalTabState {
  return {
    terminalId,
    name,
    cmdDisplay,
    xterm: null,
    fitAddon: null,
    exited: false,
    exitCode: null,
  }
}

export function TerminalPanel({ open, onToggle, socket, busy }: Props) {
  const [tabs, setTabs] = useState<TerminalTabState[]>([])
  const [activeTabIdx, setActiveTabIdx] = useState(0)
  const tabsRef = useRef<TerminalTabState[]>([])

  const [askModalOpen, setAskModalOpen] = useState(false)
  const [askModalText, setAskModalText] = useState('')
  const [askModalFollowup, setAskModalFollowup] = useState<'auto' | 'follow-up' | 'new-task'>('auto')
  const askTextareaRef = useRef<HTMLTextAreaElement | null>(null)
  // Single output buffer for all terminals: accumulates data from terminal_output
  // events that arrive before the xterm instance is ready to accept writes.
  // Keyed by terminal_id. Lives outside React state so appending never triggers
  // a re-render or causes the init effect to re-run (which was the root bug).
  const outputBufferRef = useRef<Map<string, string>>(new Map())

  // Polling heuristic: delay terminal creation when panel is animating open.
  const openRef = useRef(open)
  const panelTransitioningRef = useRef(false)
  const pendingCreatedRef = useRef<Array<{ terminal_id: string; name: string; cmd_display?: string }>>([])
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const panelDivRef = useRef<HTMLDivElement | null>(null)

  // Tooltip state: null = hidden, otherwise track position + text + animation phase.
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string; visible: boolean } | null>(null)
  const tooltipHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { openRef.current = open }, [open])

  useEffect(() => () => {
    if (tooltipHideTimerRef.current) clearTimeout(tooltipHideTimerRef.current)
  }, [])

  const showTooltip = useCallback((e: React.MouseEvent<HTMLButtonElement>, text: string) => {
    if (!text) return
    if (tooltipHideTimerRef.current) { clearTimeout(tooltipHideTimerRef.current); tooltipHideTimerRef.current = null }
    const rect = e.currentTarget.getBoundingClientRect()
    setTooltip({ x: rect.left + rect.width / 2, y: rect.top, text, visible: true })
  }, [])

  const hideTooltip = useCallback(() => {
    setTooltip(prev => prev ? { ...prev, visible: false } : null)
    tooltipHideTimerRef.current = setTimeout(() => setTooltip(null), 85)
  }, [])

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

  const clearPoll = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const createTerminalTab = useCallback((terminal_id: string, name: string, cmd_display?: string) => {
    if (tabsRef.current.some(t => t.terminalId === terminal_id)) return
    const next = [...tabsRef.current, makeTab(terminal_id, name, cmd_display ?? '')]
    tabsRef.current = next
    setTabs(next)
    setActiveTabIdx(next.length - 1)
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

    function onTerminalCreated({ terminal_id, name, cmd_display }: { terminal_id: string; name: string; cmd_display?: string }) {
      if (panelTransitioningRef.current) {
        if (!pendingCreatedRef.current.some(e => e.terminal_id === terminal_id)) {
          pendingCreatedRef.current.push({ terminal_id, name, cmd_display })
        }
        return
      }
      createTerminalTab(terminal_id, name, cmd_display)
    }

    function onTerminalOpenPanel() {
      // If the panel was closed, start polling until it has animated to its full width
      // before flushing any queued terminal_created events. This prevents xterm from
      // fitting itself against the narrow mid-transition container.
      if (!openRef.current) {
        panelTransitioningRef.current = true
        let pollCount = 0
        clearPoll()
        pollTimerRef.current = setInterval(() => {
          pollCount++
          const width = panelDivRef.current?.getBoundingClientRect().width ?? 0
          const expected = Math.min(680, Math.max(280, window.innerWidth * 0.38))
          if (width >= expected * 0.9 || pollCount >= 6) {
            clearPoll()
            panelTransitioningRef.current = false
            const pending = pendingCreatedRef.current.splice(0)
            for (const evt of pending) {
              createTerminalTab(evt.terminal_id, evt.name, evt.cmd_display)
            }
          }
        }, 500)
      }
    }

    function onTerminalSessionsState({ sessions }: { sessions: TerminalSessionState[] }) {
      const byId = new Map(tabsRef.current.map(tab => [tab.terminalId, tab]))
      const next = sessions.map(session => {
        const existing = byId.get(session.terminal_id)
        if (existing) return { ...existing, name: session.name, exited: false, exitCode: null }
        if (session.snapshot) outputBufferRef.current.set(session.terminal_id, session.snapshot)
        return makeTab(session.terminal_id, session.name, session.cmd_display ?? '')
      })
      tabsRef.current = next
      setTabs(next)
      setActiveTabIdx(idx => Math.min(idx, Math.max(0, next.length - 1)))
    }

    socket.on('terminal_output', onTerminalOutput)
    socket.on('terminal_exited', onTerminalExited)
    socket.on('terminal_created', onTerminalCreated)
    socket.on('terminal_open_panel', onTerminalOpenPanel)
    socket.on('terminal_sessions_state', onTerminalSessionsState)

    return () => {
      socket.off('terminal_output', onTerminalOutput)
      socket.off('terminal_exited', onTerminalExited)
      socket.off('terminal_created', onTerminalCreated)
      socket.off('terminal_open_panel', onTerminalOpenPanel)
      socket.off('terminal_sessions_state', onTerminalSessionsState)
      clearPoll()
      pendingCreatedRef.current = []
      panelTransitioningRef.current = false
    }
  }, [socket, updateTab, createTerminalTab, clearPoll])

  useEffect(() => {
    if (tabs.length === 0) {
      setActiveTabIdx(0)
      return
    }
    if (activeTabIdx >= tabs.length) setActiveTabIdx(tabs.length - 1)
  }, [activeTabIdx, tabs.length])

  useEffect(() => {
    if (!askModalOpen) return
    const t = setTimeout(() => askTextareaRef.current?.focus(), 50)
    return () => clearTimeout(t)
  }, [askModalOpen])

  useEffect(() => {
    if (!askModalOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setAskModalOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [askModalOpen])

  const submitAskModal = useCallback(() => {
    if (busy) return
    const tab = tabsRef.current[activeTabIdx]
    if (!tab || !askModalText.trim()) return
    const { terminalId, name, xterm } = tab
    const screen = getScreenOutput(xterm)
    const screenBlock = screen || '(no output available)'
    const text =
      `Regarding terminal [${terminalId}] (${name}), I have the following question/request.\n\n` +
      `${askModalText.trim()}\n\n` +
      `Use the \`read_open_terminal\` tool with id ${terminalId} or \`last_asked\` if the following data is not sufficient.\n\n` +
      `Terminal Screen Capture:\n\n` +
      `${screenBlock}`
    socket.emit('terminal_ask_about', { terminal_id: terminalId })
    socket.emit('user_message', { text, clientTurnId: crypto.randomUUID(), followup_behavior: askModalFollowup })
    setAskModalOpen(false)
    setAskModalText('')
    setAskModalFollowup('auto')
  }, [busy, activeTabIdx, askModalText, askModalFollowup, socket])

  const createTerminal = useCallback(() => {
    socket.emit('terminal_create', {})
  }, [socket])

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
    <div css={panelCss} ref={panelDivRef}>
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
            onMouseEnter={e => showTooltip(e, tab.cmdDisplay)}
            onMouseLeave={hideTooltip}
          >
            <span css={tabNameCss}>{tab.name || tab.terminalId}{tab.exited ? ' (exited)' : ''}</span>
            <span
              css={closeTabCss}
              role="button"
              aria-label={`Close ${tab.name || tab.terminalId}`}
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
      {activeTab && (
        <div css={footerCss}>
          <button css={askButtonCss} onClick={() => setAskModalOpen(true)}>
            Ask about this terminal
          </button>
        </div>
      )}
      {tooltip && (
        <div css={tooltipCss(tooltip.visible)} style={{ left: tooltip.x, top: tooltip.y }}>
          {tooltip.text}
        </div>
      )}
      {askModalOpen && (
        <>
          <div css={modalBackdropCss} onClick={() => setAskModalOpen(false)} />
          <div css={modalBoxCss} role="dialog" aria-modal="true" aria-label="Ask about this terminal">
            <div css={modalHeaderRowCss}>
              <span css={modalTitleCss}>Ask about this terminal</span>
              <button css={modalCloseXCss} onClick={() => setAskModalOpen(false)} aria-label="Close">×</button>
            </div>
            <div css={modalBodyCss}>
              <textarea
                ref={askTextareaRef}
                css={modalTextareaCss}
                placeholder="Type your question or request..."
                value={askModalText}
                onChange={e => setAskModalText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submitAskModal() }}
                rows={4}
              />
              <div css={modalFollowupRowCss}>
                <span css={modalFollowupLabelCss}>Follow-up</span>
                {(['auto', 'follow-up', 'new-task'] as const).map(opt => (
                  <button
                    key={opt}
                    css={modalFollowupPillCss(askModalFollowup === opt)}
                    onClick={() => setAskModalFollowup(opt)}
                  >
                    {opt === 'auto' ? 'auto-detect' : opt === 'follow-up' ? 'force-follow-up' : 'force-new-task'}
                  </button>
                ))}
              </div>
            </div>
            <div css={modalActionsRowCss}>
              <button css={modalCancelBtnCss} onClick={() => setAskModalOpen(false)}>Cancel</button>
              <button
                css={modalSubmitBtnCss(!askModalText.trim() || busy)}
                disabled={!askModalText.trim() || busy}
                onClick={submitAskModal}
              >
                Send to Agent
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
