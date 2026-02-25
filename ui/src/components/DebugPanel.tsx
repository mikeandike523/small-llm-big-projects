/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useState, useEffect } from 'react'
import Ansi from 'ansi-to-react'
import { useScrollToBottom } from '../hooks/useScrollToBottom'
import { socket } from '../socket'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SkillsInfo {
  enabled: boolean
  count: number
  path: string | null
  files: string[]
}

interface EnvInfo {
  os: string
  shell: string
}

interface BackendLogEntry {
  id: number
  text: string
}

interface Props {
  open: boolean
  onToggle: () => void
  pwd: string
  envInfo: EnvInfo | null
  skillsInfo: SkillsInfo | null
  systemPrompt: string | null
  backendLogs: BackendLogEntry[]
}

// ---------------------------------------------------------------------------
// Tab system
// ---------------------------------------------------------------------------

type TabId = 'system' | 'session' | 'project' | 'prompt' | 'logs'

const TABS: { id: TabId; label: string }[] = [
  { id: 'system',  label: 'System Info' },
  { id: 'session', label: 'Session Mem' },
  { id: 'project', label: 'Project Mem' },
  { id: 'prompt',  label: 'Sys Prompt' },
  { id: 'logs',    label: 'Backend Logs' },
]

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const scrollbarCss = css`
  &::-webkit-scrollbar { width: 4px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 2px; }
  &::-webkit-scrollbar-thumb:hover { background: #555; }
`

const panelCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d0d;
  border-right: 1px solid #1e1e1e;
  overflow: hidden;
  flex-shrink: 0;
`

const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-bottom: 1px solid #1e1e1e;
  background: #111;
  flex-shrink: 0;
  min-height: 32px;
`

const headerTitleCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #555;
`

const toggleButtonCss = css`
  background: transparent;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 13px;
  padding: 0 2px;
  line-height: 1;
  &:hover { color: #aaa; }
`

const collapsedStripCss = css`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  background: #0d0d0d;
  border-right: 1px solid #1e1e1e;
`

const tabBarCss = css`
  display: flex;
  flex-direction: row;
  height: 30px;
  border-bottom: 1px solid #1e1e1e;
  background: #0d0d0d;
  flex-shrink: 0;
  overflow: hidden;
`

const tabButtonCss = (active: boolean) => css`
  flex: 1;
  height: 100%;
  background: ${active ? '#161616' : 'transparent'};
  border: none;
  border-bottom: 2px solid ${active ? '#2563eb' : 'transparent'};
  color: ${active ? '#b0b0b0' : '#484848'};
  padding: 0 4px;
  font-family: 'Consolas', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-align: center;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  &:hover {
    color: ${active ? '#c0c0c0' : '#707070'};
    background: #141414;
  }
`

const tabContentAreaCss = css`
  position: relative;
  flex: 1;
  overflow: hidden;
`

const tabPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? 'auto' : 'none'};
  transition: opacity 0.18s ease;
  padding: 10px;
  ${scrollbarCss}
`

const promptPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? 'auto' : 'none'};
  transition: opacity 0.18s ease;
  padding: 10px;
  font-family: 'Consolas', monospace;
  font-size: 10px;
  color: #777;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  ${scrollbarCss}
`

const rowCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
`

const rowLabelCss = css`
  font-family: 'Consolas', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #444;
`

const rowValueCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #888;
  word-break: break-all;
`

const placeholderCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #333;
  font-style: italic;
  padding: 4px 0;
`

const skillsCardCss = css`
  border: 1px solid #1e1e1e;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 10px;
`

const skillsCardHeaderCss = css`
  font-family: 'Consolas', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #555;
  padding: 4px 8px;
  background: #111;
  border-bottom: 1px solid #1e1e1e;
`

const skillsCardBodyCss = css`
  ${scrollbarCss}
  max-height: 100px;
  overflow-y: auto;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
`

const skillsCardPathCss = css`
  font-family: 'Consolas', monospace;
  font-size: 9px;
  color: #4a4a4a;
  word-break: break-all;
  margin-bottom: 3px;
`

const skillsCardFileCss = css`
  font-family: 'Consolas', monospace;
  font-size: 10px;
  color: #777;
`

const logsPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? 'auto' : 'none'};
  transition: opacity 0.18s ease;
  padding: 6px;
  display: flex;
  flex-direction: column;
  ${scrollbarCss}
`

const logLineCss = css`
  font-family: 'Consolas', monospace;
  font-size: 10px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 2px;
`

// ---------------------------------------------------------------------------
// Session Memory styles
// ---------------------------------------------------------------------------

const sessionToolbarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
`

const sessionKeyCountCss = css`
  font-family: 'Consolas', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #444;
`

const refreshButtonCss = css`
  background: transparent;
  border: 1px solid #2a2a2a;
  color: #555;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  font-size: 9px;
  padding: 2px 8px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  &:hover { color: #aaa; border-color: #444; }
`

const memKeyListCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
`

const memKeyRowCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 6px;
  border: 1px solid #1a1a1a;
  border-radius: 3px;
  &:hover { border-color: #2a2a2a; background: #111; }
`

const memKeyNameCss = css`
  font-family: 'Consolas', monospace;
  font-size: 10px;
  color: #888;
  word-break: break-all;
  flex: 1;
  min-width: 0;
`

const viewButtonCss = css`
  background: transparent;
  border: 1px solid #2a2a2a;
  color: #555;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  margin-left: 6px;
  &:hover { color: #aaa; border-color: #444; }
`

// ---------------------------------------------------------------------------
// Modal styles
// ---------------------------------------------------------------------------

const modalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`

const modalCardCss = css`
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  width: 600px;
  max-width: 90vw;
  max-height: 80vh;
  overflow: hidden;
`

const modalHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #1e1e1e;
  flex-shrink: 0;
  gap: 8px;
`

const modalTitleCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #888;
  word-break: break-all;
  flex: 1;
  min-width: 0;
`

const modalCloseButtonCss = css`
  background: transparent;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
  &:hover { color: #aaa; }
`

const modalBodyCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #888;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  ${scrollbarCss}
`

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div css={rowCss}>
      <span css={rowLabelCss}>{label}</span>
      <span css={rowValueCss}>{value}</span>
    </div>
  )
}

function SkillsCard({ skillsInfo }: { skillsInfo: SkillsInfo }) {
  if (!skillsInfo.enabled) {
    return <InfoRow label="Skills" value="Disabled" />
  }
  return (
    <div css={skillsCardCss}>
      <div css={skillsCardHeaderCss}>
        {skillsInfo.count} skill{skillsInfo.count !== 1 ? 's' : ''} loaded
      </div>
      <div css={skillsCardBodyCss}>
        {skillsInfo.path && <div css={skillsCardPathCss}>{skillsInfo.path}</div>}
        {skillsInfo.files.length > 0
          ? skillsInfo.files.map(f => <div key={f} css={skillsCardFileCss}>· {f}</div>)
          : <div css={placeholderCss}>No skill files found.</div>
        }
      </div>
    </div>
  )
}

function SystemTab({ pwd, envInfo, skillsInfo }: { pwd: string; envInfo: EnvInfo | null; skillsInfo: SkillsInfo | null }) {
  return (
    <>
      {envInfo && (
        <>
          <InfoRow label="OS" value={envInfo.os} />
          <InfoRow label="Shell" value={envInfo.shell} />
        </>
      )}
      {pwd && <InfoRow label="Working Directory" value={pwd} />}
      {skillsInfo && <SkillsCard skillsInfo={skillsInfo} />}
      {!envInfo && !pwd && !skillsInfo && (
        <div css={placeholderCss}>No system info available.</div>
      )}
    </>
  )
}

function SessionMemTab({
  keys,
  onRefresh,
  onView,
}: {
  keys: string[]
  onRefresh: () => void
  onView: (key: string) => void
}) {
  return (
    <>
      <div css={sessionToolbarCss}>
        <span css={sessionKeyCountCss}>
          {keys.length} key{keys.length !== 1 ? 's' : ''}
        </span>
        <button css={refreshButtonCss} onClick={onRefresh}>Refresh</button>
      </div>
      {keys.length === 0
        ? <div css={placeholderCss}>No memory keys.</div>
        : (
          <div css={memKeyListCss}>
            {keys.map(key => (
              <div key={key} css={memKeyRowCss}>
                <span css={memKeyNameCss}>{key}</span>
                <button css={viewButtonCss} onClick={() => onView(key)}>View</button>
              </div>
            ))}
          </div>
        )
      }
    </>
  )
}

function BackendLogsTab({ logs, visible }: { logs: BackendLogEntry[]; visible: boolean }) {
  const { containerRef, scrollToBottomIfNeeded, onScroll } = useScrollToBottom<HTMLDivElement>()

  useEffect(() => {
    scrollToBottomIfNeeded()
  }, [logs, scrollToBottomIfNeeded])

  return (
    <div ref={containerRef} css={logsPanelCss(visible)} onScroll={onScroll}>
      {logs.length === 0
        ? <div css={placeholderCss}>No logs yet.</div>
        : logs.map(entry => (
            <div key={entry.id} css={logLineCss}>
              <Ansi>{entry.text}</Ansi>
            </div>
          ))
      }
    </div>
  )
}

// ---------------------------------------------------------------------------
// DebugPanel
// ---------------------------------------------------------------------------

interface MemModal {
  key: string
  value: string
  loading: boolean
}

export function DebugPanel({ open, onToggle, pwd, envInfo, skillsInfo, systemPrompt, backendLogs }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>('system')
  const [sessionMemKeys, setSessionMemKeys] = useState<string[]>([])
  const [memModal, setMemModal] = useState<MemModal | null>(null)

  // Listen for session memory socket events
  useEffect(() => {
    function onMemoryKeys({ keys }: { keys: string[] }) {
      setSessionMemKeys(keys)
    }
    function onMemoryValue({ key, value, found }: { key: string; value: string; found: boolean }) {
      setMemModal(prev => {
        if (!prev || prev.key !== key) return prev
        return { key, value: found ? value : '(key not found)', loading: false }
      })
    }
    socket.on('session_memory_keys_update', onMemoryKeys)
    socket.on('session_memory_value', onMemoryValue)
    return () => {
      socket.off('session_memory_keys_update', onMemoryKeys)
      socket.off('session_memory_value', onMemoryValue)
    }
  }, [])

  // Fetch keys when the session tab becomes active
  useEffect(() => {
    if (open && activeTab === 'session') {
      socket.emit('get_session_memory_keys')
    }
  }, [open, activeTab])

  function refreshMemoryKeys() {
    socket.emit('get_session_memory_keys')
  }

  function viewMemoryValue(key: string) {
    setMemModal({ key, value: '', loading: true })
    socket.emit('get_session_memory_value', { key })
  }

  if (!open) {
    return (
      <div css={collapsedStripCss}>
        <button css={toggleButtonCss} onClick={onToggle} title="Open debug panel">»</button>
      </div>
    )
  }

  return (
    <>
      {memModal && (
        <div css={modalOverlayCss} onClick={() => setMemModal(null)}>
          <div css={modalCardCss} onClick={e => e.stopPropagation()}>
            <div css={modalHeaderCss}>
              <span css={modalTitleCss}>{memModal.key}</span>
              <button css={modalCloseButtonCss} onClick={() => setMemModal(null)}>×</button>
            </div>
            <div css={modalBodyCss}>
              {memModal.loading ? 'Loading...' : memModal.value}
            </div>
          </div>
        </div>
      )}

      <div css={panelCss}>
        <div css={headerCss}>
          <span css={headerTitleCss}>Debug</span>
          <button css={toggleButtonCss} onClick={onToggle} title="Close debug panel">«</button>
        </div>

        <div css={tabBarCss}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              css={tabButtonCss(activeTab === tab.id)}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div css={tabContentAreaCss}>
          <div css={tabPanelCss(activeTab === 'system')}>
            <SystemTab pwd={pwd} envInfo={envInfo} skillsInfo={skillsInfo} />
          </div>
          <div css={tabPanelCss(activeTab === 'session')}>
            <SessionMemTab
              keys={sessionMemKeys}
              onRefresh={refreshMemoryKeys}
              onView={viewMemoryValue}
            />
          </div>
          <div css={tabPanelCss(activeTab === 'project')}>
            <div css={placeholderCss}>Under construction.</div>
          </div>
          <div css={promptPanelCss(activeTab === 'prompt')}>
            {systemPrompt !== null
              ? systemPrompt
              : <span css={placeholderCss}>Not yet received.</span>
            }
          </div>
          <BackendLogsTab logs={backendLogs} visible={activeTab === 'logs'} />
        </div>
      </div>
    </>
  )
}
