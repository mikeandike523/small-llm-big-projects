/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useEffect, useState } from 'react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionDefaults {
  pin_project_memory: boolean
  interim_response_as_thinking: boolean
  record_traces: boolean
  load_skills: boolean
  load_tools: boolean
  load_startup_tool_calls: boolean
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  sessionDefaults: SessionDefaults
  onCreated: (sessionId: string) => void
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const backdropCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`

const dialogCss = css`
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 28px 32px;
  width: 480px;
  max-width: 95vw;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
  font-family: 'Fira Code', 'Consolas', monospace;
  color: #d0d0d0;
  &::-webkit-scrollbar { width: 5px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 3px; }
`

const dialogTitleCss = css`
  font-size: 15px;
  font-weight: 600;
  color: #c8c8c8;
  letter-spacing: 1px;
`

const fieldLabelCss = css`
  font-size: 11px;
  color: #666;
  margin-bottom: 6px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
`

const cwdRowCss = css`
  display: flex;
  gap: 8px;
  align-items: stretch;
`

const cwdInputCss = css`
  flex: 1;
  background: #0f0f0f;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  &:focus { border-color: #3a3a5a; }
`

const browseBtnCss = (loading: boolean) => css`
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: ${loading ? '#444' : '#888'};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 12px;
  cursor: ${loading ? 'not-allowed' : 'pointer'};
  white-space: nowrap;
  transition: border-color 0.12s;
  &:hover { border-color: ${loading ? '#2a2a2a' : '#444'}; }
`

const checkboxSectionCss = css`
  display: flex;
  flex-direction: column;
  gap: 10px;
`

const checkboxRowCss = css`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
`

const checkboxInputCss = css`
  margin-top: 2px;
  accent-color: #5577ee;
  cursor: pointer;
  flex-shrink: 0;
`

const checkboxTextCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
`

const checkboxLabelCss = css`
  font-size: 12px;
  color: #c0c0c0;
`

const checkboxDescCss = css`
  font-size: 10px;
  color: #444;
`

const footerCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
`

const cancelBtnCss = css`
  background: none;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #666;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 16px;
  cursor: pointer;
  &:hover { border-color: #444; color: #888; }
`

const createBtnCss = (loading: boolean) => css`
  background: ${loading ? '#1a1a2e' : '#1e2650'};
  border: 1px solid ${loading ? '#2a3a6e' : '#3a5aee'};
  border-radius: 5px;
  color: ${loading ? '#5566aa' : '#8aacff'};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 20px;
  cursor: ${loading ? 'not-allowed' : 'pointer'};
  transition: background 0.12s;
  &:hover { background: ${loading ? '#1a1a2e' : '#222a5e'}; }
`

const errorMsgCss = css`
  font-size: 11px;
  color: #cc6666;
  background: #1a0a0a;
  border: 1px solid #3a1a1a;
  border-radius: 4px;
  padding: 8px 12px;
`

// ---------------------------------------------------------------------------
// Checkbox option config
// ---------------------------------------------------------------------------

interface CheckOption {
  key: keyof SessionDefaults
  label: string
  flag: string
  desc: string
}

const OPTIONS: CheckOption[] = [
  {
    key: 'pin_project_memory',
    label: 'Pin project memory',
    flag: '--pin-project-memory',
    desc: 'Scope project memory to this session\'s working directory.',
  },
  {
    key: 'record_traces',
    label: 'Enable trace recording',
    flag: '--etr',
    desc: 'Record every LLM completion for fine-tuning export.',
  },
  {
    key: 'load_skills',
    label: 'Load skills',
    flag: '--load-skills',
    desc: 'Load custom skills from a skills/ directory in the working directory.',
  },
  {
    key: 'load_tools',
    label: 'Load custom tools',
    flag: '--load-tools',
    desc: 'Load custom tools from a tools/ directory in the working directory.',
  },
  {
    key: 'load_startup_tool_calls',
    label: 'Run startup tool calls',
    flag: '--load-startup-tool-calls',
    desc: 'Execute tool calls from startup_tool_calls.json on session start.',
  },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NewSessionDialog({ sessionDefaults, onCreated, onClose }: Props) {
  const [cwd, setCwd] = useState('')
  const [flags, setFlags] = useState<SessionDefaults>(() => ({ ...sessionDefaults }))
  const [browsing, setBrowsing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch default workspace directory as default CWD on mount
  useEffect(() => {
    fetch('/api/system-info')
      .then(r => r.json())
      .then(d => {
        if (d.workspace_dir) setCwd(d.workspace_dir)
        else if (d.home_dir) setCwd(d.home_dir)
      })
      .catch(() => {})
  }, [])

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handleBrowse() {
    setBrowsing(true)
    try {
      const res = await fetch('/api/folder-pick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initial_dir: cwd }),
      })
      const data = await res.json()
      if (data.path) setCwd(data.path)
    } catch {
      // silently ignore — user can type path manually
    } finally {
      setBrowsing(false)
    }
  }

  async function handleCreate() {
    if (creating) return
    setCreating(true)
    setError(null)

    const payload: Record<string, unknown> = {
      initial_cwd: cwd,
      pin_project_memory: flags.pin_project_memory,
      interim_response_as_thinking: sessionDefaults.interim_response_as_thinking,
      record_traces: flags.record_traces,
    }
    if (flags.load_skills) payload.skills_path = `${cwd}/skills`
    if (flags.load_tools) payload.custom_tools_path = `${cwd}/tools`
    if (flags.load_startup_tool_calls) payload.startup_tool_calls_path = `${cwd}/startup_tool_calls.json`

    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error ?? `Server returned ${res.status}`)
      }
      const data = await res.json()
      if (!data.session_id) throw new Error('Server did not return a session_id.')
      onCreated(data.session_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
      setCreating(false)
    }
  }

  function toggleFlag(key: keyof SessionDefaults) {
    setFlags(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div css={backdropCss} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div css={dialogCss}>
        <div css={dialogTitleCss}>New Session</div>

        <div>
          <div css={fieldLabelCss}>Working Directory</div>
          <div css={cwdRowCss}>
            <input
              css={cwdInputCss}
              type="text"
              value={cwd}
              onChange={e => setCwd(e.target.value)}
              placeholder="/path/to/project"
              spellCheck={false}
            />
            <button
              css={browseBtnCss(browsing)}
              onClick={handleBrowse}
              disabled={browsing}
              title="Open folder picker"
            >
              {browsing ? '...' : 'Browse'}
            </button>
          </div>
        </div>

        <div>
          <div css={fieldLabelCss}>Options</div>
          <div css={checkboxSectionCss}>
            {OPTIONS.map(opt => (
              <label key={opt.key} css={checkboxRowCss}>
                <input
                  type="checkbox"
                  css={checkboxInputCss}
                  checked={flags[opt.key]}
                  onChange={() => toggleFlag(opt.key)}
                />
                <div css={checkboxTextCss}>
                  <span css={checkboxLabelCss}>
                    {opt.label}
                    <span style={{ color: '#3a3a5a', marginLeft: 6 }}>{opt.flag}</span>
                  </span>
                  <span css={checkboxDescCss}>{opt.desc}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        {error && <div css={errorMsgCss}>{error}</div>}

        <div css={footerCss}>
          <button css={cancelBtnCss} onClick={onClose} disabled={creating}>
            Cancel
          </button>
          <button
            css={createBtnCss(creating)}
            onClick={handleCreate}
            disabled={creating || !cwd.trim()}
          >
            {creating ? 'Creating...' : 'Create Session'}
          </button>
        </div>
      </div>
    </div>
  )
}
