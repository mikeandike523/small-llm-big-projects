/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useState } from 'react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SkillsInfo {
  enabled: boolean
  count: number
  path: string | null
}

interface EnvInfo {
  os: string
  shell: string
}

interface Props {
  open: boolean
  onToggle: () => void
  pwd: string
  envInfo: EnvInfo | null
  skillsInfo: SkillsInfo | null
}

// ---------------------------------------------------------------------------
// Tab system
// ---------------------------------------------------------------------------

type TabId = 'system' | 'session' | 'project'

const TABS: { id: TabId; label: string }[] = [
  { id: 'system',  label: 'System Info' },
  { id: 'session', label: 'Session Memory' },
  { id: 'project', label: 'Project Memory' },
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
  border-bottom: 1px solid #1e1e1e;
  background: #0d0d0d;
  flex-shrink: 0;
  overflow: hidden;
`

const tabButtonCss = (active: boolean) => css`
  flex: 1;
  background: ${active ? '#161616' : 'transparent'};
  border: none;
  border-bottom: 2px solid ${active ? '#2563eb' : 'transparent'};
  color: ${active ? '#b0b0b0' : '#484848'};
  padding: 5px 4px;
  font-family: 'Consolas', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
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
      {skillsInfo && (
        <>
          <InfoRow label="Skills" value={skillsInfo.enabled ? `Enabled (${skillsInfo.count})` : 'Disabled'} />
          {skillsInfo.enabled && skillsInfo.path && (
            <InfoRow label="Skills Path" value={skillsInfo.path} />
          )}
        </>
      )}
      {!envInfo && !pwd && !skillsInfo && (
        <div css={placeholderCss}>No system info available.</div>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// DebugPanel
// ---------------------------------------------------------------------------

export function DebugPanel({ open, onToggle, pwd, envInfo, skillsInfo }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>('system')

  if (!open) {
    return (
      <div css={collapsedStripCss}>
        <button css={toggleButtonCss} onClick={onToggle} title="Open debug panel">»</button>
      </div>
    )
  }

  return (
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
          <div css={placeholderCss}>Under construction.</div>
        </div>
        <div css={tabPanelCss(activeTab === 'project')}>
          <div css={placeholderCss}>Under construction.</div>
        </div>
      </div>
    </div>
  )
}
