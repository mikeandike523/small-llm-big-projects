/** @jsxImportSource @emotion/react */
import { css, keyframes } from '@emotion/react'
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import NewSessionDialog, { type SessionDefaults } from './NewSessionDialog'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionSummary {
  session_id: string
  initial_cwd: string
  current_cwd: string
  created_at: number
  turn_count: number
  active_turn: boolean
  interim_response_as_thinking: boolean
  record_traces: boolean
  task_titles: string[]
  pin_project_memory: boolean
  skills_path: string | null
  custom_tools_path: string | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(ts: number): string {
  if (!ts) return 'unknown'
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function cwdBasename(cwd: string): string {
  const norm = cwd.replace(/\\/g, '/')
  return norm.split('/').filter(Boolean).pop() ?? cwd
}

// ---------------------------------------------------------------------------
// Animations
// ---------------------------------------------------------------------------

const pulse = keyframes`
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.5; transform: scale(1.3); }
`

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const scrollbarCss = css`
  &::-webkit-scrollbar { width: 6px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #2f4f86; border-radius: 3px; }
  &::-webkit-scrollbar-thumb:hover { background: #4f73b3; }
`

const containerCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f0f0f;
  color: #e0e0e0;
  font-family: 'Fira Code', 'Consolas', monospace;
`

const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 28px;
  border-bottom: 1px solid #1e1e1e;
  flex-shrink: 0;
`

const titleCss = css`
  font-size: 18px;
  font-weight: 700;
  color: #f2f6ff;
  letter-spacing: 2px;
  text-transform: uppercase;
`

const subtitleCss = css`
  font-size: 11px;
  color: #dbe5ff;
  margin-top: 2px;
  letter-spacing: 1px;
`

const newSessionBtnCss = css`
  background: #1a1a2e;
  color: #7b9cff;
  border: 1px solid #2a3a6e;
  border-radius: 6px;
  padding: 8px 18px;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  &:hover:not(:disabled) {
    background: #222244;
    border-color: #4a6aee;
  }
  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`

const bodyScrollCss = css`
  ${scrollbarCss};
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
`

const sessionGridCss = css`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
`

const sessionCardCss = css`
  background: #0d131e;
  border: 1px solid #22304d;
  border-radius: 8px;
  padding: 16px 18px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  display: flex;
  flex-direction: column;
  gap: 8px;
  &:hover {
    background: #101a28;
    border-color: #3b5b92;
  }
`

const cardHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
`

const cwdLineCss = css`
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
`

const cwdBaseCss = css`
  font-size: 14px;
  font-weight: 600;
  color: #f2f6ff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`

const cwdPathCss = css`
  font-size: 11px;
  color: #dbe5ff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
`

const activeDotCss = css`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3ccc6c;
  flex-shrink: 0;
  animation: ${pulse} 1.4s ease-in-out infinite;
`

const idleDotCss = css`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #101722;
  border: 1px solid #30405f;
  flex-shrink: 0;
`

const cardMetaCss = css`
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 11px;
  color: #e6edff;
`

const metaBadgeCss = css`
  background: #101722;
  border: 1px solid #30405f;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 10px;
  color: #eef3ff;
`

const currentCwdLineCss = css`
  font-size: 10px;
  color: #3a8a5a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`

const taskTitlesCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
`

const taskTitleItemCss = css`
  font-size: 11px;
  color: #e6edff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`

const trashBtnCss = css`
  background: none;
  border: none;
  cursor: pointer;
  color: #cc2222;
  font-size: 15px;
  padding: 2px 4px;
  border-radius: 4px;
  line-height: 1;
  opacity: 0.7;
  transition: opacity 0.12s, background 0.12s;
  flex-shrink: 0;
  &:hover {
    opacity: 1;
    background: #2a0a0a;
  }
`

const modalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`

const modalBoxCss = css`
  background: #181818;
  border: 1px solid #3a1a1a;
  border-radius: 10px;
  padding: 28px 32px;
  max-width: 420px;
  width: 90%;
  display: flex;
  flex-direction: column;
  gap: 18px;
  font-family: 'Fira Code', 'Consolas', monospace;
`

const modalTitleCss = css`
  font-size: 15px;
  font-weight: 700;
  color: #cc4444;
  letter-spacing: 1px;
`

const modalBodyCss = css`
  font-size: 12px;
  color: #eef3ff;
  line-height: 1.6;
`

const modalActionsCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
`

const modalCancelBtnCss = css`
  background: none;
  border: 1px solid #30405f;
  border-radius: 5px;
  color: #eef3ff;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  &:hover { border-color: #8aa4d8; color: #fff; }
`

const modalDeleteBtnCss = css`
  background: #2a0a0a;
  border: 1px solid #cc2222;
  border-radius: 5px;
  color: #ee4444;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  font-weight: 600;
  &:hover { background: #3a0a0a; border-color: #ff4444; }
  &:disabled { opacity: 0.5; cursor: not-allowed; }
`

const emptyStateCss = css`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  height: 60%;
  color: #e6edff;
  font-size: 14px;
  text-align: center;
`

const errorBannerCss = css`
  background: #1a0a0a;
  border: 1px solid #3a1a1a;
  border-radius: 6px;
  padding: 12px 18px;
  color: #cc6666;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
`

const retryBtnCss = css`
  background: none;
  border: 1px solid #3a1a1a;
  border-radius: 4px;
  color: #cc6666;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 11px;
  font-family: inherit;
  &:hover { border-color: #cc6666; }
`

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showNewSession, setShowNewSession] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [sessionDefaults, setSessionDefaults] = useState<SessionDefaults | null>(null)
  const [sessionDefaultsError, setSessionDefaultsError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/session-defaults')
      .then(r => {
        if (!r.ok) throw new Error(`Server returned ${r.status}`)
        return r.json()
      })
      .then((d: SessionDefaults) => {
        setSessionDefaults(d)
        setSessionDefaultsError(null)
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : 'Unknown error'
        console.error('[slbp] Failed to load session defaults:', msg)
        setSessionDefaultsError(msg)
      })
  }, [])

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch('/api/sessions')
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      const data: SessionSummary[] = await res.json()
      setSessions(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach server')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
    const interval = setInterval(fetchSessions, 3000)
    return () => clearInterval(interval)
  }, [fetchSessions])

  function openSession(sessionId: string) {
    navigate(`/session?sessionId=${sessionId}`)
  }

  function handleSessionCreated(sessionId: string) {
    setShowNewSession(false)
    navigate(`/session?sessionId=${sessionId}`)
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      const res = await fetch(`/api/sessions/${deleteTarget.session_id}`, { method: 'DELETE' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        alert(body.error ?? `Delete failed (${res.status})`)
      } else {
        setSessions(prev => prev.filter(s => s.session_id !== deleteTarget.session_id))
      }
    } catch {
      alert('Could not reach server')
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }

  return (
    <div css={containerCss}>
      <div css={headerCss}>
        <div>
          <div css={titleCss}>SLBP</div>
          <div css={subtitleCss}>small llm, big projects</div>
        </div>
        <button
          css={newSessionBtnCss}
          onClick={() => setShowNewSession(true)}
          disabled={sessionDefaults === null}
          title={sessionDefaults === null ? 'Loading session defaults...' : undefined}
        >
          + New Session
        </button>
      </div>

      <div css={bodyScrollCss}>
        {error && (
          <div css={errorBannerCss}>
            <span>Server unreachable: {error}</span>
            <button css={retryBtnCss} onClick={fetchSessions}>Retry</button>
          </div>
        )}
        {sessionDefaultsError && (
          <div css={errorBannerCss}>
            <span>Failed to load session defaults: {sessionDefaultsError} — New Session is disabled.</span>
          </div>
        )}

        {!loading && sessions.length === 0 && !error && (
          <div css={emptyStateCss}>
            <div style={{ fontSize: 32, opacity: 0.15 }}>◈</div>
            <div>No sessions yet.</div>
            <div style={{ fontSize: 12, color: '#dbe5ff' }}>
              Click <strong style={{ color: '#f2f6ff' }}>+ New Session</strong> to start one.
            </div>
          </div>
        )}

        {sessions.length > 0 && (
          <div css={sessionGridCss}>
            {sessions.map(s => (
              <SessionCard
                key={s.session_id}
                session={s}
                onClick={() => openSession(s.session_id)}
                onDelete={e => { e.stopPropagation(); setDeleteTarget(s) }}
              />
            ))}
          </div>
        )}
      </div>

      {showNewSession && sessionDefaults && (
        <NewSessionDialog
          sessionDefaults={sessionDefaults}
          onCreated={handleSessionCreated}
          onClose={() => setShowNewSession(false)}
        />
      )}

      {deleteTarget && (
        <div css={modalOverlayCss} onClick={() => !deleting && setDeleteTarget(null)}>
          <div css={modalBoxCss} onClick={e => e.stopPropagation()}>
            <div css={modalTitleCss}>Delete Session?</div>
            <div css={modalBodyCss}>
              This will permanently delete all data for session{' '}
              <strong style={{ color: '#ccc' }}>{deleteTarget.session_id.slice(0, 8)}</strong>
              {' '}({cwdBasename(deleteTarget.initial_cwd)}), including all turns, memory, and cached state.
              This cannot be undone.
            </div>
            <div css={modalActionsCss}>
              <button css={modalCancelBtnCss} onClick={() => setDeleteTarget(null)} disabled={deleting}>
                Cancel
              </button>
              <button css={modalDeleteBtnCss} onClick={confirmDelete} disabled={deleting}>
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session card
// ---------------------------------------------------------------------------

function SessionCard({
  session,
  onClick,
  onDelete,
}: {
  session: SessionSummary
  onClick: () => void
  onDelete: (e: React.MouseEvent) => void
}) {
  const base = cwdBasename(session.initial_cwd)
  const fullPath = session.initial_cwd.replace(/\\/g, '/')
  const currentPath = session.current_cwd?.replace(/\\/g, '/')
  const cwdChanged = currentPath && currentPath !== fullPath

  const titles = session.task_titles ?? []
  const MAX_TITLES = 4

  return (
    <div css={sessionCardCss} onClick={onClick}>
      <div css={cardHeaderCss}>
        <div css={cwdLineCss}>
          <span css={cwdBaseCss} title={fullPath}>{base}</span>
          <span css={cwdPathCss} title={fullPath}>{fullPath}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <div css={session.active_turn ? activeDotCss : idleDotCss} title={session.active_turn ? 'Turn in progress' : 'Idle'} />
          <button
            css={trashBtnCss}
            onClick={onDelete}
            title="Delete session"
          >
            🗑
          </button>
        </div>
      </div>

      {cwdChanged && (
        <div css={currentCwdLineCss} title={`Current CWD: ${currentPath}`}>
          ↳ {currentPath}
        </div>
      )}

      {titles.length > 0 && (
        <div css={taskTitlesCss}>
          {titles.slice(-MAX_TITLES).map((t, i) => (
            <div key={i} css={taskTitleItemCss} title={t}>• {t}</div>
          ))}
          {titles.length > MAX_TITLES && (
            <div css={taskTitleItemCss} style={{ color: '#dbe5ff' }}>
              + {titles.length - MAX_TITLES} more
            </div>
          )}
        </div>
      )}

      <div css={cardMetaCss}>
        <span>{session.turn_count} {session.turn_count === 1 ? 'turn' : 'turns'}</span>
        <span>{relativeTime(session.created_at)}</span>
        {session.interim_response_as_thinking && <span css={metaBadgeCss}>irat</span>}
        {session.record_traces && <span css={metaBadgeCss}>traces</span>}
        {session.pin_project_memory && <span css={metaBadgeCss}>pin-mem</span>}
        {session.skills_path && <span css={metaBadgeCss} title={session.skills_path}>skills</span>}
        {session.custom_tools_path && <span css={metaBadgeCss} title={session.custom_tools_path}>tools</span>}
      </div>

      <div style={{ fontSize: 10, color: '#dbe5ff', fontFamily: 'monospace' }}>
        {session.session_id.slice(0, 8)}
      </div>
    </div>
  )
}
