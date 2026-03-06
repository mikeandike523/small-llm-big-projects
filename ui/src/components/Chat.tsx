/** @jsxImportSource @emotion/react */
import React from 'react'
import { css, keyframes } from '@emotion/react'
import { useEffect, useRef, useState, useCallback } from 'react'
import { type Socket } from 'socket.io-client'
import { createSocket } from '../socket'
import { useScrollToBottom } from '../hooks/useScrollToBottom'
import { TextPresenter } from './TextPresenter'
import { DebugPanel } from './DebugPanel'
import Ansi from 'ansi-to-react'
import type { Turn, ToolCallEntry, TodoItem, ApprovalItem } from '../types'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TOOL_CHARS = 80
const MAX_LOGS = 100

// ---------------------------------------------------------------------------
// Shared scrollbar styles
// ---------------------------------------------------------------------------

const scrollbarCss = css`
  &::-webkit-scrollbar { width: 6px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 3px; }
  &::-webkit-scrollbar-thumb:hover { background: #555; }
`

// ---------------------------------------------------------------------------
// Types (local-only)
// ---------------------------------------------------------------------------

interface BackendLogEntry {
  id: number
  text: string
}

// ---------------------------------------------------------------------------
// Turn helpers
// ---------------------------------------------------------------------------

function newTurn(id: string, userText: string): Turn {
  return {
    id,
    userText,
    exchanges: [],
    todoItems: [],
    approvalItems: [],
    completed: false,
    streaming: true,
    isInterimStreaming: false,
    interimCharCount: 0,
  }
}

function backendTurnToFrontendTurn(d: {
  id: string
  user_text: string
  exchanges: {
    assistant_content: string
    reasoning: string
    tool_calls: {
      id: string
      name: string
      args: Record<string, unknown>
      result?: string
      was_stubbed?: boolean
      started_at?: number
      finished_at?: number
    }[]
    is_final: boolean
  }[]
  todo_snapshot: TodoItem[]
  was_impossible: boolean
  impossible_reason?: string
  was_cancelled?: boolean
  completed: boolean
}): Turn {
  return {
    id: d.id,
    userText: d.user_text,
    exchanges: d.exchanges.map(ex => ({
      assistantContent: ex.assistant_content,
      reasoning: ex.reasoning,
      toolCalls: ex.tool_calls.map(tc => ({
        id: tc.id,
        name: tc.name,
        args: tc.args,
        result: tc.result,
        wasStubbed: tc.was_stubbed,
        startedAt: tc.started_at ?? undefined,
        finishedAt: tc.finished_at ?? undefined,
      })),
      isFinal: ex.is_final,
    })),
    todoItems: d.todo_snapshot ?? [],
    approvalItems: [],
    impossible: d.was_impossible ? (d.impossible_reason ?? 'Task was impossible') : undefined,
    cancelled: d.was_cancelled ? 'Turn was cancelled' : undefined,
    completed: d.completed,
    streaming: false,
    isInterimStreaming: false,
    interimCharCount: 0,
  }
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const appLayoutCss = css`
  display: flex;
  flex-direction: row;
  height: 100vh;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 15px;
  background: #0f0f0f;
  color: #e0e0e0;
`

const debugPanelWrapperCss = (open: boolean) => css`
  width: ${open ? '20%' : '28px'};
  min-width: ${open ? '160px' : '28px'};
  max-width: ${open ? '320px' : '28px'};
  transition: width 0.2s ease, min-width 0.2s ease, max-width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  height: 100%;
`

const mainAreaCss = css`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
`

const threadCss = css`
  ${scrollbarCss}
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
`

const inputBarCss = css`
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #2a2a2a;
  background: #151515;
`

const textareaCss = css`
  flex: 1;
  background: #1e1e1e;
  color: #e0e0e0;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
  &:focus {
    border-color: #555;
  }
`

const sendButtonCss = css`
  position: relative;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 20px;
  font-size: 14px;
  cursor: pointer;
  align-self: flex-end;
  height: 40px;
  overflow: hidden;
  &:disabled {
    background: #1e3a6e;
    cursor: not-allowed;
  }
`

const _spin = keyframes`
  to { transform: rotate(360deg); }
`

const spinnerCss = css`
  position: absolute;
  inset: 0;
  margin: auto;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`

const userBubbleCss = css`
  ${scrollbarCss}
  background: #1d4ed8;
  border: 1px solid #2d5fe8;
  border-radius: 16px 16px 4px 16px;
  padding: 12px 16px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  align-self: flex-end;
  max-height: 180px;
  overflow-y: auto;
  box-shadow: 0 2px 10px rgba(29, 78, 216, 0.3);
`

const assistantBubbleCss = css`
  background: #1c1c1c;
  border: 1px solid #303030;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  word-break: break-word;
  line-height: 1.5;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
`

const streamingPlaceholderCss = css`
  background: #1c1c1c;
  border: 1px solid #303030;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  color: #555;
`

const interimBubbleCss = css`
  background: #111;
  border: 1px solid #252525;
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 11px;
  color: #484848;
  font-family: 'Consolas', monospace;
  font-style: italic;
`

const impossibleBubbleCss = css`
  background: #1a0a00;
  border: 1px solid #7a3000;
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
`

const impossibleLabelCss = css`
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #c05010;
  font-weight: 600;
`

const impossibleReasonCss = css`
  font-size: 13px;
  color: #d08040;
  line-height: 1.5;
  word-break: break-word;
`

const interruptedBubbleCss = css`
  background: #1a1020;
  border: 1px solid #4a2a6a;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 11px;
  color: #8060a0;
  font-style: italic;
`

const cancelledBubbleCss = css`
  background: #0a1020;
  border: 1px solid #2a3a60;
  border-radius: 10px;
  padding: 8px 14px;
`

const cancelledLabelCss = css`
  font-size: 12px;
  color: #4a6090;
  font-weight: 500;
`

const cancelButtonCss = css`
  background: #2a1010;
  color: #c06060;
  border: 1px solid #5a2020;
  border-radius: 8px;
  padding: 0 14px;
  font-size: 13px;
  cursor: pointer;
  align-self: flex-end;
  height: 40px;
  font-family: inherit;
  transition: background 0.15s;
  &:hover { background: #3a1515; }
`

const cancellingLabelCss = css`
  align-self: flex-end;
  height: 40px;
  display: flex;
  align-items: center;
  font-size: 13px;
  color: #666;
  font-style: italic;
  white-space: nowrap;
`

const reasoningWrapperCss = css`
  color: #7aa2e0;
  font-size: 13px;
  font-style: italic;
  background: #111827;
  border: 1px solid #1e3a5f;
  border-radius: 10px;
  padding: 12px 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
`

const toolCallCss = css`
  flex-shrink: 0;
  border: 1px solid #3d2f5a;
  border-radius: 10px;
  overflow: hidden;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
`

const toolHeaderCss = css`
  background: #2a1a4a;
  color: #b48be0;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
`

const viewFullButtonCss = css`
  background: transparent;
  color: #8860c0;
  border: 1px solid #4a2a7a;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background 0.15s, color 0.15s;
  &:hover {
    background: #3a1a5a;
    color: #c090f0;
  }
`

const toolArgsCss = css`
  background: #16162a;
  color: #a0a0c0;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #252545;
`

const toolResultCss = css`
  background: #0a1a0a;
  color: #7ec87e;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #1a3a1a;
  & code {
    display: block;
    font-family: inherit;
    background: transparent;
    padding: 0;
    margin: 0;
  }
`

const toolCallsGroupCss = css`
  ${scrollbarCss}
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
`

const startupCardCss = css`
  border: 1px solid #2a3a2a;
  border-radius: 12px;
  background: #0d150d;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
  overflow: hidden;
`

const startupCardHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #111a11;
  border-bottom: 1px solid #1e2e1e;
  font-size: 12px;
  color: #70a070;
  font-family: 'Consolas', monospace;
  text-transform: uppercase;
  letter-spacing: 0.06em;
`

const startupCardBodyCss = css`
  padding: 12px;
`

const inlineSpinnerCss = css`
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid rgba(100, 180, 100, 0.3);
  border-top-color: #70c870;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
  vertical-align: middle;
`

const startupDoneBadgeCss = css`
  font-size: 11px;
  color: #50a050;
`

const headerBarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 16px;
  border-bottom: 1px solid #1a1a1a;
  flex-shrink: 0;
`

const statusCss = css`
  font-size: 11px;
  color: #c8c8c8;
  font-family: 'Consolas', monospace;
  white-space: nowrap;
`

const turnContainerCss = css`
  display: grid;
  grid-template-columns: 3fr 2fr 2fr 1.5fr;
  gap: 24px;
  padding: 20px 24px;
  border: 1px solid #3a3a3a;
  border-radius: 12px;
  background: #141414;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
`

const leftColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 14px;
`

const rightColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 12px;
`

const todoColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-left: 1px solid #2a2a2a;
  padding-left: 16px;
  min-width: 0;
`

const todoHeaderCss = css`
  font-size: 11px;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
`

const todoListScrollCss = css`
  overflow: auto;
  max-height: 320px;
  &::-webkit-scrollbar { width: 6px; height: 6px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 3px; }
  &::-webkit-scrollbar-thumb:hover { background: #555; }
`

const todoItemOpenCss = css`
  font-size: 12px;
  color: #c0c0c0;
  font-family: 'Consolas', monospace;
  padding: 2px 0;
  white-space: nowrap;
`

const todoItemClosedCss = css`
  font-size: 12px;
  color: #505050;
  font-family: 'Consolas', monospace;
  padding: 2px 0;
  text-decoration: line-through;
  white-space: nowrap;
`

const todoEmptyCss = css`
  font-size: 12px;
  color: #3a3a3a;
  font-style: italic;
`

const approvalColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-left: 1px solid #2a2a2a;
  padding-left: 16px;
  min-width: 0;
`

const approvalHeaderCss = css`
  font-size: 11px;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
`

const approvalEmptyCss = css`
  font-size: 12px;
  color: #3a3a3a;
  font-style: italic;
`

const approvalPendingCardCss = css`
  background: #1a1200;
  border: 1px solid #6a4800;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`

const approvalToolNameCss = css`
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: #d4a030;
  font-weight: 600;
  word-break: break-all;
`

const approvalArgsCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #907040;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
  ${scrollbarCss}
`

const approvalButtonRowCss = css`
  display: flex;
  gap: 6px;
`

const approveButtonCss = css`
  flex: 1;
  background: #14532d;
  color: #4ade80;
  border: 1px solid #166534;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  transition: background 0.15s;
  &:hover { background: #166534; }
`

const denyButtonCss = css`
  flex: 1;
  background: #450a0a;
  color: #f87171;
  border: 1px solid #7f1d1d;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  transition: background 0.15s;
  &:hover { background: #7f1d1d; }
`

const approvalScrollContainerCss = css`
  ${scrollbarCss}
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
`

const approvalResolvedBubbleCss = (approved: boolean) => css`
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: ${approved ? '#4ade80' : '#f87171'};
  padding: 4px 8px;
  border-radius: 4px;
  background: ${approved ? '#0a1a0a' : '#1a0a0a'};
  border: 1px solid ${approved ? '#1a4a1a' : '#4a1a1a'};
  word-break: break-all;
`

const approvalTimedOutBubbleCss = css`
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: #888840;
  padding: 4px 8px;
  border-radius: 4px;
  background: #111100;
  border: 1px solid #333300;
  word-break: break-all;
`

const _approvalPulse = keyframes`
  0%, 100% { opacity: 0.75; box-shadow: 0 0 6px #d4a03060; }
  50%       { opacity: 1;    box-shadow: 0 0 18px #d4a030b0; }
`

const approvalBannerCss = css`
  background: #1a1200;
  border: 1px solid #6a4800;
  border-radius: 6px;
  padding: 5px 10px;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  font-weight: 600;
  color: #d4a030;
  text-align: center;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  animation: ${_approvalPulse} 1.8s ease-in-out infinite;
  flex-shrink: 0;
`

const loadingOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
`

const loadingCardCss = css`
  background: #ffffff;
  border-radius: 16px;
  padding: 36px 52px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.25);
`

const loadingTextCss = css`
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 15px;
  color: #444;
  font-weight: 500;
`

const loadingSpinnerCss = css`
  width: 32px;
  height: 32px;
  border: 3px solid rgba(37, 99, 235, 0.2);
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: ${_spin} 0.8s linear infinite;
`

const _streamPulse = keyframes`
  0%, 100% { opacity: 0.35; }
  50%       { opacity: 1; }
`

const streamingDotCss = css`
  display: inline-block;
  width: 6px;
  height: 6px;
  background: #70a0ff;
  border-radius: 50%;
  margin-left: 6px;
  vertical-align: middle;
  animation: ${_streamPulse} 1s ease-in-out infinite;
`

const elapsedTimeCss = css`
  font-size: 11px;
  color: #7060a0;
  font-family: 'Consolas', monospace;
  flex-shrink: 0;
  margin-left: 6px;
`

const streamingResultCss = css`
  background: #050e05;
  color: #5a8a5a;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #0f200f;
`

const modalOverlayBaseCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  transition: opacity 0.2s ease;
`

const modalOverlayVisibleCss = css`
  opacity: 1;
  pointer-events: auto;
`

const modalOverlayHiddenCss = css`
  opacity: 0;
  pointer-events: none;
`

const modalCardCss = css`
  background: #181818;
  border: 1px solid #444;
  border-radius: 12px;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.8);
  width: 80%;
  max-width: 900px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
`

const modalHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #333;
  background: #1e1e1e;
  flex-shrink: 0;
`

const modalTitleCss = css`
  color: #7ec87e;
  font-family: 'Consolas', monospace;
  font-size: 13px;
  font-style: normal;
`

const modalCloseButtonCss = css`
  background: transparent;
  color: #888;
  border: none;
  font-size: 22px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
  &:hover { color: #ccc; }
`

const modalBodyCss = css`
  ${scrollbarCss}
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  font-family: 'Consolas', monospace;
  font-size: 13px;
  color: #7ec87e;
  white-space: pre-wrap;
  word-break: break-word;
  background: #0a1a0a;
  line-height: 1.6;
  & code {
    display: block;
    font-family: inherit;
    background: transparent;
    padding: 0;
    margin: 0;
  }
`

// ---------------------------------------------------------------------------
// ElapsedTimer
// ---------------------------------------------------------------------------

function ElapsedTimer({ startedAt, finishedAt }: { startedAt?: number; finishedAt?: number }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!startedAt || finishedAt) return
    const id = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(id)
  }, [startedAt, finishedAt])

  if (!startedAt) return null
  const elapsed = ((finishedAt ?? now) - startedAt) / 1000
  return <span css={elapsedTimeCss}>{elapsed.toFixed(1)}s</span>
}

// ---------------------------------------------------------------------------
// StartupToolCallsCard
// ---------------------------------------------------------------------------

function StartupToolCallsCard({
  toolCalls,
  done,
  onViewFull,
}: {
  toolCalls: ToolCallEntry[]
  done: boolean
  onViewFull: (content: string) => void
}) {
  const { containerRef, scrollToBottomIfNeeded, onScroll } = useScrollToBottom<HTMLDivElement>({
    persistId: 'startup-tools',
  })

  useEffect(() => {
    if (!done) scrollToBottomIfNeeded()
  }, [toolCalls, done, scrollToBottomIfNeeded])

  return (
    <div css={startupCardCss}>
      <div css={startupCardHeaderCss}>
        <span>Startup Tool Calls</span>
        {done
          ? <span css={startupDoneBadgeCss}>done ({toolCalls.length})</span>
          : <span css={inlineSpinnerCss} />
        }
      </div>
      <div css={startupCardBodyCss}>
        <div css={toolCallsGroupCss} ref={containerRef} onScroll={onScroll}>
          {toolCalls.map(tc => {
            const hasResult = tc.result !== undefined
            const truncated = hasResult && tc.result!.length > MAX_TOOL_CHARS
            const displayResult = hasResult
              ? truncated
                ? tc.result!.slice(0, MAX_TOOL_CHARS) + `... (${tc.result!.length - MAX_TOOL_CHARS} more)`
                : tc.result!
              : undefined

            return (
              <div key={tc.id} css={toolCallCss}>
                <div css={toolHeaderCss}>
                  <span>⚙ {tc.name}</span>
                  {truncated && (
                    <button css={viewFullButtonCss} onClick={() => onViewFull(tc.result!)}>
                      view full
                    </button>
                  )}
                </div>
                {Object.keys(tc.args).length > 0 && (
                  <div css={toolArgsCss}>{JSON.stringify(tc.args, null, 2)}</div>
                )}
                {hasResult && (
                  <div css={toolResultCss}><Ansi>{displayResult}</Ansi></div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Hierarchical todo renderer
// ---------------------------------------------------------------------------

function renderTodoItems(items: TodoItem[], depth: number = 0): React.ReactNode[] {
  return items.flatMap(item => {
    const pathStr = item.item_path + '.'
    const rows: React.ReactNode[] = [
      <div
        key={pathStr}
        css={item.status === 'closed' ? todoItemClosedCss : todoItemOpenCss}
        style={{ paddingLeft: depth * 14 }}
        title={item.text}
      >
        {pathStr} {item.text}
      </div>
    ]
    if (item.children && item.children.length > 0) {
      rows.push(...renderTodoItems(item.children, depth + 1))
    }
    return rows
  })
}

// ---------------------------------------------------------------------------
// ToolCallCard
// ---------------------------------------------------------------------------

const MAX_STREAMING_CHARS = 300

function ToolCallCard({ tc, onViewFull }: { tc: ToolCallEntry; onViewFull: (c: string) => void }) {
  const hasResult = tc.result !== undefined
  const isStreaming = !hasResult && tc.streamingResult !== undefined
  const truncated = hasResult && tc.result!.length > MAX_TOOL_CHARS

  let displayResult: string | undefined
  if (hasResult) {
    displayResult = truncated
      ? tc.result!.slice(0, MAX_TOOL_CHARS) + `... (${tc.result!.length - MAX_TOOL_CHARS} more)`
      : tc.result!
  } else if (isStreaming) {
    const sr = tc.streamingResult!
    displayResult = sr.length > MAX_STREAMING_CHARS
      ? `[...+${sr.length - MAX_STREAMING_CHARS} chars]\n` + sr.slice(-MAX_STREAMING_CHARS)
      : sr
  }

  return (
    <div css={toolCallCss}>
      <div css={toolHeaderCss}>
        <span>
          ⚙ {tc.name}
          {isStreaming && <span css={streamingDotCss} />}
        </span>
        <span css={css`display: flex; align-items: center; gap: 6px;`}>
          <ElapsedTimer startedAt={tc.startedAt} finishedAt={tc.finishedAt} />
          {truncated && (
            <button css={viewFullButtonCss} onClick={() => onViewFull(tc.result!)}>
              view full
            </button>
          )}
        </span>
      </div>
      {Object.keys(tc.args).length > 0 && (
        <div css={toolArgsCss}>{JSON.stringify(tc.args, null, 2)}</div>
      )}
      {isStreaming && displayResult !== undefined && (
        <div css={streamingResultCss}><Ansi>{displayResult}</Ansi></div>
      )}
      {hasResult && (
        <div css={toolResultCss}><Ansi>{displayResult}</Ansi></div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ToolApprovalBubble
// ---------------------------------------------------------------------------

function ToolApprovalBubble({
  item,
  onApprove,
  onDeny,
}: {
  item: ApprovalItem
  onApprove: (id: string) => void
  onDeny: (id: string) => void
}) {
  if (item.timedOut) {
    return <div css={approvalTimedOutBubbleCss}>⏱ timed out: {item.tool_name}</div>
  }
  if (item.resolved) {
    return (
      <div css={approvalResolvedBubbleCss(item.resolved.approved)}>
        {item.resolved.approved ? '✓' : '✗'} {item.tool_name}
      </div>
    )
  }
  return (
    <div css={approvalPendingCardCss}>
      <div css={approvalToolNameCss}>{item.tool_name}</div>
      {Object.keys(item.args).length > 0 && (
        <div css={approvalArgsCss}>{JSON.stringify(item.args, null, 2)}</div>
      )}
      <div css={approvalButtonRowCss}>
        <button css={approveButtonCss} onClick={() => onApprove(item.id)}>Approve</button>
        <button css={denyButtonCss} onClick={() => onDeny(item.id)}>Deny</button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TurnContainer
// ---------------------------------------------------------------------------

function TurnContainer({
  turn,
  onViewFull,
  onApprove,
  onDeny,
}: {
  turn: Turn
  onViewFull: (content: string) => void
  onApprove: (id: string) => void
  onDeny: (id: string) => void
}) {
  const { todoItems, approvalItems, impossible, cancelled, exchanges, streaming, isInterimStreaming, interimCharCount, interrupted } = turn

  const { containerRef: toolsRef, scrollToBottomIfNeeded: scrollTools, onScroll: onToolsScroll } =
    useScrollToBottom<HTMLDivElement>({ persistId: `tools-${turn.id}` })

  const approvalScrollRef = useRef<HTMLDivElement>(null)
  const hasPendingApproval = approvalItems.some(a => !a.resolved && !a.timedOut)
  useEffect(() => {
    if (approvalScrollRef.current) {
      approvalScrollRef.current.scrollTop = approvalScrollRef.current.scrollHeight
    }
  }, [approvalItems.length, hasPendingApproval])

  // Collect all tool calls from all exchanges (for the tool calls panel)
  const allToolCalls = exchanges.flatMap(ex => ex.toolCalls)

  // Display content: final exchange's content, or last exchange's content if it has no tool calls (live streaming)
  const lastExchange = exchanges[exchanges.length - 1]
  const finalExchange = exchanges.find(ex => ex.isFinal)
  const liveContent = streaming && lastExchange && !lastExchange.isFinal && lastExchange.toolCalls.length === 0
    ? lastExchange.assistantContent
    : undefined
  const displayContent = finalExchange?.assistantContent ?? liveContent ?? ''

  // Reasoning from the latest exchange that has any reasoning
  const reasoning = [...exchanges].reverse().find(ex => ex.reasoning)?.reasoning ?? ''

  const isStreamingFinal = streaming && !isInterimStreaming
  const showPlaceholder = streaming && !displayContent && !isInterimStreaming && allToolCalls.length === 0

  useEffect(() => {
    if (streaming) scrollTools()
  }, [allToolCalls.length, streaming, scrollTools])

  return (
    <div css={turnContainerCss}>
      {/* Left column: user message + AI content + impossible notice */}
      <div css={leftColumnCss}>
        <div css={userBubbleCss}>{turn.userText}</div>
        {(interimCharCount > 0 || isInterimStreaming) && (
          <div css={interimBubbleCss}>
            AI interim response: {interimCharCount} chars
          </div>
        )}
        {displayContent ? (
          <div css={assistantBubbleCss}>
            <TextPresenter
              content={displayContent}
              maxHeight={600}
              streaming={isStreamingFinal}
            />
          </div>
        ) : null}
        {showPlaceholder && (
          <div css={streamingPlaceholderCss}>…</div>
        )}
        {impossible && (
          <div css={impossibleBubbleCss}>
            <span css={impossibleLabelCss}>Task impossible</span>
            <span css={impossibleReasonCss}>{impossible}</span>
          </div>
        )}
        {cancelled && (
          <div css={cancelledBubbleCss}>
            <span css={cancelledLabelCss}>Turn cancelled</span>
          </div>
        )}
        {interrupted && (
          <div css={interruptedBubbleCss}>Connection interrupted</div>
        )}
      </div>

      {/* Right column: reasoning + tool calls */}
      <div css={rightColumnCss}>
        {reasoning ? (
          <div css={reasoningWrapperCss}>
            <TextPresenter
              content={reasoning}
              maxHeight={200}
              streaming={streaming}
              initialMode="plain"
              showToggle={false}
            />
          </div>
        ) : null}
        {allToolCalls.length > 0 && (
          <div css={toolCallsGroupCss} ref={toolsRef} onScroll={onToolsScroll}>
            {allToolCalls.map(tc => (
              <ToolCallCard key={tc.id} tc={tc} onViewFull={onViewFull} />
            ))}
          </div>
        )}
      </div>

      {/* Third column: todo list */}
      <div css={todoColumnCss}>
        <div css={todoHeaderCss}>Todo</div>
        {todoItems.length === 0
          ? <div css={todoEmptyCss}>empty</div>
          : <div css={todoListScrollCss}>
              {renderTodoItems(todoItems)}
            </div>
        }
      </div>

      {/* Fourth column: approval */}
      <div css={approvalColumnCss}>
        <div css={approvalHeaderCss}>Approval</div>
        {approvalItems.length === 0 ? (
          <div css={approvalEmptyCss}>—</div>
        ) : (
          <>
            <div css={approvalScrollContainerCss} ref={approvalScrollRef}>
              {approvalItems.map(item => (
                <ToolApprovalBubble key={item.id} item={item} onApprove={onApprove} onDeny={onDeny} />
              ))}
            </div>
            {hasPendingApproval && (
              <div css={approvalBannerCss}>⚠ Approval needed</div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Chat() {
  // Session ID: read from sessionStorage on mount (idempotent — repeated mounts
  // return the same ID; only generates a new UUID the very first time).
  const [sessionId] = useState<string>(() => {
    let id = sessionStorage.getItem('session_id')
    if (!id) {
      id = crypto.randomUUID()
      sessionStorage.setItem('session_id', id)
    }
    return id
  })

  // Socket: created once per component instance with the stable sessionId.
  // autoConnect:false means it does not connect until socket.connect() is called.
  const socketRef = useRef<Socket | null>(null)
  if (!socketRef.current) {
    socketRef.current = createSocket(sessionId)
  }
  const socket = socketRef.current

  const [thread, setThread] = useState<Turn[]>([])
  const [startupToolCalls, setStartupToolCalls] = useState<ToolCallEntry[]>([])
  const [startupDone, setStartupDone] = useState(false)
  const [inputText, setInputText] = useState('')
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [modalContent, setModalContent] = useState<string | null>(null)
  const [pwd, setPwd] = useState<string>('')
  const [skillsInfo, setSkillsInfo] = useState<{ enabled: boolean; count: number; path: string | null; files: string[] } | null>(null)
  const [envInfo, setEnvInfo] = useState<{ os: string; shell: string; initialCwd: string } | null>(null)
  const [toolsInfo, setToolsInfo] = useState<{
    totalCount: number
    builtinCount: number
    builtinPath: string
    names: string[]
    customPlugins: { name: string; count: number; path: string }[] | null
  } | null>(null)
  const [debugOpen, setDebugOpen] = useState(true)
  const [systemPrompt, setSystemPrompt] = useState<string | null>(null)
  const [backendLogs, setBackendLogs] = useState<BackendLogEntry[]>([])
  const [isLoadingBackendState, setIsLoadingBackendState] = useState(false)

  const {
    containerRef: threadRef,
    isAtBottom,
    scrollToBottomIfNeeded,
    onScroll: handleScroll,
  } = useScrollToBottom<HTMLDivElement>({ persistId: 'thread' })

  useEffect(() => {
    scrollToBottomIfNeeded()
  }, [thread, scrollToBottomIfNeeded])

  // ---------------------------------------------------------------------------
  // lastEventId — persisted to sessionStorage
  // ---------------------------------------------------------------------------

  const getLastEventId = () => sessionStorage.getItem('lastEventId') ?? '0-0'
  const updateLastEventId = (id: string) => {
    sessionStorage.setItem('lastEventId', id)
  }

  // ---------------------------------------------------------------------------
  // Thread helpers
  // ---------------------------------------------------------------------------

  const updateTurn = useCallback((turnId: string, updater: (t: Turn) => Turn) => {
    setThread(prev => prev.map(t => t.id === turnId ? updater(t) : t))
  }, [])

  // ---------------------------------------------------------------------------
  // Replay processor
  // ---------------------------------------------------------------------------

  const applyReplayEvent = useCallback((type: string, data: Record<string, unknown>) => {
    const turnId = (data.turn_id as string | undefined) ?? ''

    switch (type) {
      case 'turn_start': {
        const id = data.turn_id as string
        const userText = data.user_text as string
        setThread(prev => {
          if (prev.some(t => t.id === id)) return prev
          return [...prev, { ...newTurn(id, userText), streaming: false }]
        })
        break
      }
      case 'replay_content_snapshot': {
        const exchangeIdx = data.exchange_idx as number
        const assistantContent = (data.assistant_content as string) ?? ''
        const reasoning = (data.reasoning as string) ?? ''
        updateTurn(turnId, t => {
          const exchanges = [...t.exchanges]
          while (exchanges.length <= exchangeIdx) {
            exchanges.push({ assistantContent: '', reasoning: '', toolCalls: [], isFinal: false })
          }
          exchanges[exchangeIdx] = { ...exchanges[exchangeIdx], assistantContent, reasoning }
          return { ...t, exchanges }
        })
        break
      }
      case 'tool_call': {
        const tc: ToolCallEntry = {
          id: data.id as string,
          name: data.name as string,
          args: data.args as Record<string, unknown>,
        }
        updateTurn(turnId, t => {
          // Find or create the current exchange (last non-final)
          const exchanges = [...t.exchanges]
          const idx = exchanges.findIndex((ex, i) => !ex.isFinal && i === exchanges.length - 1)
          if (idx >= 0) {
            if (!exchanges[idx].toolCalls.some(e => e.id === tc.id)) {
              exchanges[idx] = { ...exchanges[idx], toolCalls: [...exchanges[idx].toolCalls, tc] }
            }
          } else {
            exchanges.push({ assistantContent: '', reasoning: '', toolCalls: [tc], isFinal: false })
          }
          return { ...t, exchanges }
        })
        break
      }
      case 'tool_call_start': {
        const id = data.id as string
        const startedAt = data.started_at as number
        updateTurn(turnId, t => ({
          ...t,
          exchanges: t.exchanges.map(ex => ({
            ...ex,
            toolCalls: ex.toolCalls.map(tc => tc.id === id ? { ...tc, startedAt } : tc),
          })),
        }))
        break
      }
      case 'tool_result': {
        const id = data.id as string
        const result = data.result as string
        const finishedAt = data.finished_at as number | undefined
        updateTurn(turnId, t => ({
          ...t,
          exchanges: t.exchanges.map(ex => ({
            ...ex,
            toolCalls: ex.toolCalls.map(tc =>
              tc.id === id ? { ...tc, result, ...(finishedAt !== undefined ? { finishedAt } : {}) } : tc
            ),
          })),
        }))
        break
      }
      case 'begin_interim_stream':
        updateTurn(turnId, t => ({ ...t, isInterimStreaming: true }))
        break
      case 'begin_final_summary':
        updateTurn(turnId, t => ({ ...t, isInterimStreaming: false }))
        break
      case 'todo_list_update':
        updateTurn(turnId, t => ({ ...t, todoItems: data.items as TodoItem[] }))
        break
      case 'report_impossible':
        updateTurn(turnId, t => ({ ...t, impossible: data.reason as string }))
        break
      case 'turn_cancelled':
        updateTurn(turnId, t => ({ ...t, cancelled: 'Turn was cancelled' }))
        break
      case 'approval_request': {
        const item: ApprovalItem = {
          id: data.id as string,
          tool_name: data.tool_name as string,
          args: data.args as Record<string, unknown>,
        }
        updateTurn(turnId, t => ({ ...t, approvalItems: [...t.approvalItems, item] }))
        break
      }
      case 'approval_resolved': {
        const approved = data.approved as boolean
        const id = data.id as string
        updateTurn(turnId, t => ({
          ...t,
          approvalItems: t.approvalItems.map(a =>
            a.id === id ? { ...a, resolved: { approved } } : a
          ),
        }))
        break
      }
      case 'approval_timeout': {
        const id = data.id as string
        updateTurn(turnId, t => ({
          ...t,
          approvalItems: t.approvalItems.map(a =>
            a.id === id ? { ...a, timedOut: true } : a
          ),
        }))
        break
      }
      case 'message_done': {
        const content = data.content as string | null
        updateTurn(turnId, t => {
          const exchanges = [...t.exchanges]
          if (content !== null && exchanges.length > 0) {
            const last = exchanges[exchanges.length - 1]
            exchanges[exchanges.length - 1] = { ...last, assistantContent: content, isFinal: true }
          }
          return { ...t, completed: true, streaming: false, isInterimStreaming: false, exchanges }
        })
        break
      }
      case 'error': {
        const message = data.message as string
        updateTurn(turnId, t => {
          const exchanges = [...t.exchanges]
          if (exchanges.length === 0) {
            exchanges.push({ assistantContent: `⚠ ${message}`, reasoning: '', toolCalls: [], isFinal: true })
          } else {
            const last = exchanges[exchanges.length - 1]
            exchanges[exchanges.length - 1] = { ...last, assistantContent: `⚠ ${message}`, isFinal: true }
          }
          return { ...t, completed: true, streaming: false, exchanges }
        })
        break
      }
      case 'pwd_update':
        setPwd(data.path as string)
        break
    }
  }, [updateTurn])

  // ---------------------------------------------------------------------------
  // Socket wiring
  // ---------------------------------------------------------------------------

  useEffect(() => {
    function onConnect() {
      setConnected(true)
      setBusy(false)
      setCancelling(false)
      setIsLoadingBackendState(true)
      // Mark any streaming turns as interrupted (they'll be cleared by event replay if still running)
      setThread(prev => prev.map(t =>
        t.streaming ? { ...t, streaming: false, interrupted: true } : t
      ))
      socket.emit('resume_session', { lastEventId: getLastEventId() })
      socket.emit('get_pwd')
      socket.emit('get_skills_info')
      socket.emit('get_env_info')
      socket.emit('get_system_prompt')
      socket.emit('get_tools_info')
    }
    function onDisconnect() { setConnected(false) }
    function onPwdUpdate({ path }: { path: string }) { setPwd(path) }
    function onSkillsInfo(data: { enabled: boolean; count: number; path: string | null; files: string[] }) { setSkillsInfo(data) }
    function onEnvInfo(data: { os: string; shell: string; initialCwd: string }) { setEnvInfo(data) }
    function onToolsInfo(data: { totalCount: number; builtinCount: number; builtinPath: string; names: string[]; customPlugins: { name: string; count: number; path: string }[] | null }) { setToolsInfo(data) }
    function onSystemPrompt({ text }: { text: string }) { setSystemPrompt(text) }
    function onBackendLog({ id, text }: { id: number; text: string }) {
      setBackendLogs(prev => {
        const next = [...prev, { id, text }]
        return next.length > MAX_LOGS ? next.slice(next.length - MAX_LOGS) : next
      })
    }

    function onStartupToolCall({ id, name, args }: { id: string; name: string; args: Record<string, unknown> }) {
      setStartupToolCalls(prev => [...prev, { id, name, args }])
    }
    function onStartupToolResult({ id, result }: { id: string; result: string }) {
      setStartupToolCalls(prev => prev.map(tc => tc.id === id ? { ...tc, result } : tc))
    }
    function onStartupToolCallsDone() {
      setStartupDone(true)
    }

    // Session state (response to resume_session)
    function onSessionState(data: {
      startupDone?: boolean
      completedTurns?: unknown[]
      currentTurn?: unknown
      schemaInvalid?: boolean
    }) {
      if (data.schemaInvalid) {
        // Schema mismatch — no event_replay will follow, so clear loading now
        setIsLoadingBackendState(false)
        setThread([])
        setStartupToolCalls([])
        setStartupDone(false)
        socket.emit('run_startup_tool_calls')
        return
      }

      // Rebuild thread from completed turns
      const turns: Turn[] = data.completedTurns
        ? (data.completedTurns as Parameters<typeof backendTurnToFrontendTurn>[0][]).map(backendTurnToFrontendTurn)
        : []

      // If there is an in-progress turn at restore time, append it as streaming.
      // Event replay will fill in any content/tool-calls that arrived since lastEventId.
      // If the agent already finished, the replayed message_done will mark it completed.
      if (data.currentTurn) {
        const inProgress = backendTurnToFrontendTurn(
          data.currentTurn as Parameters<typeof backendTurnToFrontendTurn>[0]
        )
        inProgress.streaming = true
        inProgress.isInterimStreaming = false
        inProgress.interimCharCount = 0
        turns.push(inProgress)
        setBusy(true)
      }

      setThread(turns)

      if (data.startupDone !== undefined) {
        setStartupDone(data.startupDone)
        if (!data.startupDone) {
          // First-ever session: run startup tools now that we know they haven't run yet
          socket.emit('run_startup_tool_calls')
        }
      }
    }

    // Event replay (always emitted after session_state, possibly with empty list)
    function onEventReplay({ events }: { events: { id: string; type: string; data: Record<string, unknown> }[] }) {
      if (events && events.length > 0) {
        // Clear interrupted state on any streaming turns before replaying
        setThread(prev => prev.map(t => t.interrupted ? { ...t, interrupted: false, streaming: true } : t))

        for (const ev of events) {
          if (ev.data.event_id) updateLastEventId(ev.data.event_id as string)
          applyReplayEvent(ev.type, ev.data)
        }
        updateLastEventId(events[events.length - 1].id)
      }

      // Replay complete — safe to show UI now
      setIsLoadingBackendState(false)
    }

    // Live event handlers (mirror replay logic but also track lastEventId)
    function onTurnStart(data: { event_id?: string; turn_id: string; user_text: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const id = data.turn_id
      setThread(prev => {
        if (prev.some(t => t.id === id)) return prev
        return [...prev, newTurn(id, data.user_text)]
      })
      isAtBottom.current = true
    }

    function onToken(data: { type: 'reasoning' | 'content'; text: string; turn_id?: string }) {
      const turnId = data.turn_id ?? ''
      if (!turnId) return
      updateTurn(turnId, t => {
        if (!t.streaming) return t
        if (t.isInterimStreaming && data.type === 'content') {
          return { ...t, interimCharCount: t.interimCharCount + data.text.length }
        }
        const exchanges = [...t.exchanges]
        const lastEx = exchanges[exchanges.length - 1]
        // If no exchange yet, or last exchange has tool calls (meaning a new LLM call started), create a new one
        if (!lastEx || lastEx.toolCalls.length > 0) {
          exchanges.push({
            assistantContent: data.type === 'content' ? data.text : '',
            reasoning: data.type === 'reasoning' ? data.text : '',
            toolCalls: [],
            isFinal: false,
          })
        } else {
          const idx = exchanges.length - 1
          exchanges[idx] = {
            ...exchanges[idx],
            assistantContent: data.type === 'content'
              ? exchanges[idx].assistantContent + data.text
              : exchanges[idx].assistantContent,
            reasoning: data.type === 'reasoning'
              ? exchanges[idx].reasoning + data.text
              : exchanges[idx].reasoning,
          }
        }
        return { ...t, exchanges }
      })
    }

    function onBeginInterimStream(data: { event_id?: string; turn_id?: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({ ...t, isInterimStreaming: true }))
    }

    function onBeginFinalSummary(data: { event_id?: string; turn_id?: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      // Just clear the interim streaming flag; the next token event will create the new exchange
      updateTurn(turnId, t => ({ ...t, isInterimStreaming: false }))
    }

    function onToolCall(data: { event_id?: string; turn_id?: string; id: string; name: string; args: Record<string, unknown> }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      const tc: ToolCallEntry = { id: data.id, name: data.name, args: data.args }
      updateTurn(turnId, t => {
        const exchanges = [...t.exchanges]
        const lastIdx = exchanges.length - 1
        if (lastIdx >= 0 && !exchanges[lastIdx].isFinal) {
          exchanges[lastIdx] = { ...exchanges[lastIdx], toolCalls: [...exchanges[lastIdx].toolCalls, tc] }
        } else {
          exchanges.push({ assistantContent: '', reasoning: '', toolCalls: [tc], isFinal: false })
        }
        return { ...t, exchanges }
      })
    }

    function onToolCallStart(data: { event_id?: string; turn_id?: string; id: string; started_at: number }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      const startedAt = data.started_at
      updateTurn(turnId, t => ({
        ...t,
        exchanges: t.exchanges.map(ex => ({
          ...ex,
          toolCalls: ex.toolCalls.map(tc => tc.id === data.id ? { ...tc, startedAt } : tc),
        })),
      }))
    }

    function onToolResultChunk(data: { turn_id?: string; id: string; chunk: string }) {
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({
        ...t,
        exchanges: t.exchanges.map(ex => ({
          ...ex,
          toolCalls: ex.toolCalls.map(tc =>
            tc.id === data.id
              ? { ...tc, streamingResult: (tc.streamingResult ?? '') + data.chunk }
              : tc
          ),
        })),
      }))
    }

    function onToolResult(data: { event_id?: string; turn_id?: string; id: string; result: string; started_at?: number; finished_at?: number }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      const { id, result } = data
      const finishedAt = data.finished_at
      updateTurn(turnId, t => ({
        ...t,
        exchanges: t.exchanges.map(ex => ({
          ...ex,
          toolCalls: ex.toolCalls.map(tc =>
            tc.id === id ? { ...tc, result, ...(finishedAt !== undefined ? { finishedAt } : {}) } : tc
          ),
        })),
      }))
    }

    function onMessageDone(data: { event_id?: string; turn_id?: string; content: string | null }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      const content = data.content
      updateTurn(turnId, t => {
        const exchanges = [...t.exchanges]
        if (content !== null && exchanges.length > 0) {
          const last = exchanges[exchanges.length - 1]
          exchanges[exchanges.length - 1] = { ...last, assistantContent: content, isFinal: true }
        } else if (content !== null) {
          exchanges.push({ assistantContent: content, reasoning: '', toolCalls: [], isFinal: true })
        }
        return { ...t, completed: true, streaming: false, isInterimStreaming: false, exchanges }
      })
      setBusy(false)
      setCancelling(false)
    }

    function onError(data: { event_id?: string; turn_id?: string; message: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      const message = data.message
      if (turnId) {
        updateTurn(turnId, t => {
          const exchanges = [...t.exchanges]
          if (exchanges.length === 0) {
            exchanges.push({ assistantContent: `⚠ ${message}`, reasoning: '', toolCalls: [], isFinal: true })
          } else {
            const last = exchanges[exchanges.length - 1]
            exchanges[exchanges.length - 1] = { ...last, assistantContent: `⚠ ${message}`, isFinal: true }
          }
          return { ...t, completed: true, streaming: false, exchanges }
        })
      }
      setBusy(false)
    }

    function onReportImpossible(data: { event_id?: string; turn_id?: string; reason: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({ ...t, impossible: data.reason }))
    }

    function onTurnCancelled(data: { event_id?: string; turn_id?: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({ ...t, cancelled: 'Turn was cancelled' }))
    }

    function onTodoListUpdate(data: { event_id?: string; turn_id?: string; items: TodoItem[] }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({ ...t, todoItems: data.items }))
    }

    function onApprovalRequest(data: { event_id?: string; turn_id?: string; id: string; tool_name: string; args: Record<string, unknown> }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      const item: ApprovalItem = { id: data.id, tool_name: data.tool_name, args: data.args }
      updateTurn(turnId, t => ({ ...t, approvalItems: [...t.approvalItems, item] }))
    }

    function onApprovalResolved(data: { event_id?: string; turn_id?: string; id: string; approved: boolean }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({
        ...t,
        approvalItems: t.approvalItems.map(a =>
          a.id === data.id ? { ...a, resolved: { approved: data.approved } } : a
        ),
      }))
    }

    function onApprovalTimeout(data: { event_id?: string; turn_id?: string; id: string; tool_name: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({
        ...t,
        approvalItems: t.approvalItems.map(a =>
          a.id === data.id ? { ...a, timedOut: true } : a
        ),
      }))
    }

    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    socket.on('pwd_update', onPwdUpdate)
    socket.on('skills_info', onSkillsInfo)
    socket.on('env_info', onEnvInfo)
    socket.on('tools_info', onToolsInfo)
    socket.on('system_prompt', onSystemPrompt)
    socket.on('backend_log', onBackendLog)
    socket.on('startup_tool_call', onStartupToolCall)
    socket.on('startup_tool_result', onStartupToolResult)
    socket.on('startup_tool_calls_done', onStartupToolCallsDone)
    socket.on('session_state', onSessionState)
    socket.on('event_replay', onEventReplay)
    socket.on('turn_start', onTurnStart)
    socket.on('token', onToken)
    socket.on('begin_interim_stream', onBeginInterimStream)
    socket.on('begin_final_summary', onBeginFinalSummary)
    socket.on('tool_call', onToolCall)
    socket.on('tool_call_start', onToolCallStart)
    socket.on('tool_result_chunk', onToolResultChunk)
    socket.on('tool_result', onToolResult)
    socket.on('message_done', onMessageDone)
    socket.on('error', onError)
    socket.on('report_impossible', onReportImpossible)
    socket.on('turn_cancelled', onTurnCancelled)
    socket.on('todo_list_update', onTodoListUpdate)
    socket.on('approval_request', onApprovalRequest)
    socket.on('approval_resolved', onApprovalResolved)
    socket.on('approval_timeout', onApprovalTimeout)

    // Connect after all handlers are registered so we never miss the connect event
    socket.connect()

    return () => {
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
      socket.off('pwd_update', onPwdUpdate)
      socket.off('skills_info', onSkillsInfo)
      socket.off('env_info', onEnvInfo)
      socket.off('tools_info', onToolsInfo)
      socket.off('system_prompt', onSystemPrompt)
      socket.off('backend_log', onBackendLog)
      socket.off('startup_tool_call', onStartupToolCall)
      socket.off('startup_tool_result', onStartupToolResult)
      socket.off('startup_tool_calls_done', onStartupToolCallsDone)
      socket.off('session_state', onSessionState)
      socket.off('event_replay', onEventReplay)
      socket.off('turn_start', onTurnStart)
      socket.off('token', onToken)
      socket.off('begin_interim_stream', onBeginInterimStream)
      socket.off('begin_final_summary', onBeginFinalSummary)
      socket.off('tool_call', onToolCall)
      socket.off('tool_call_start', onToolCallStart)
      socket.off('tool_result_chunk', onToolResultChunk)
      socket.off('tool_result', onToolResult)
      socket.off('message_done', onMessageDone)
      socket.off('error', onError)
      socket.off('report_impossible', onReportImpossible)
      socket.off('turn_cancelled', onTurnCancelled)
      socket.off('todo_list_update', onTodoListUpdate)
      socket.off('approval_request', onApprovalRequest)
      socket.off('approval_resolved', onApprovalResolved)
      socket.off('approval_timeout', onApprovalTimeout)
      socket.disconnect()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [socket, applyReplayEvent, updateTurn])

  // ---------------------------------------------------------------------------
  // Approval actions
  // ---------------------------------------------------------------------------

  const approve = useCallback((id: string) => {
    socket.emit('approval_response', { id, approved: true })
  }, [])

  const deny = useCallback((id: string) => {
    socket.emit('approval_response', { id, approved: false })
  }, [])

  const cancelTurn = useCallback(() => {
    socket.emit('cancel_turn')
    setCancelling(true)
  }, [socket])

  // ---------------------------------------------------------------------------
  // Send
  // ---------------------------------------------------------------------------

  const send = useCallback(() => {
    const text = inputText.trim()
    if (!text || busy || !connected) return

    const clientTurnId = crypto.randomUUID()
    socket.emit('user_message', { text, clientTurnId })
    setBusy(true)
    setInputText('')
    isAtBottom.current = true
  }, [inputText, busy, connected, isAtBottom])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div css={appLayoutCss}>
      {/* Loading backdrop — shown while waiting for session_state or during large event replays */}
      {isLoadingBackendState && (
        <div css={loadingOverlayCss}>
          <div css={loadingCardCss}>
            <div css={loadingSpinnerCss} />
            <span css={loadingTextCss}>loading backend state...</span>
          </div>
        </div>
      )}

      {/* Debug panel */}
      <div css={debugPanelWrapperCss(debugOpen)}>
        <DebugPanel
          open={debugOpen}
          onToggle={() => setDebugOpen(o => !o)}
          pwd={pwd}
          envInfo={envInfo}
          skillsInfo={skillsInfo}
          toolsInfo={toolsInfo}
          systemPrompt={systemPrompt}
          backendLogs={backendLogs}
          socket={socket}
        />
      </div>

      {/* Main content area */}
      <div css={mainAreaCss}>
        {/* Shared modal for full tool result */}
        <div
          css={[modalOverlayBaseCss, modalContent !== null ? modalOverlayVisibleCss : modalOverlayHiddenCss]}
          onClick={() => setModalContent(null)}
        >
          <div css={modalCardCss} onClick={e => e.stopPropagation()}>
            <div css={modalHeaderCss}>
              <span css={modalTitleCss}>Tool Result</span>
              <button css={modalCloseButtonCss} onClick={() => setModalContent(null)}>×</button>
            </div>
            <div css={modalBodyCss}><Ansi>{modalContent ?? ''}</Ansi></div>
          </div>
        </div>

        <div css={headerBarCss}>
          <span css={statusCss}>{connected ? '●' : '○'} {connected ? 'connected' : 'disconnected'}</span>
        </div>
        <div css={threadCss} ref={threadRef} onScroll={handleScroll}>
          {startupToolCalls.length > 0 && (
            <StartupToolCallsCard
              toolCalls={startupToolCalls}
              done={startupDone}
              onViewFull={setModalContent}
            />
          )}
          {thread.map(turn => (
            <TurnContainer
              key={turn.id}
              turn={turn}
              onViewFull={setModalContent}
              onApprove={approve}
              onDeny={deny}
            />
          ))}
        </div>
        <div css={inputBarCss}>
          <textarea
            css={textareaCss}
            rows={3}
            placeholder="Send a message… (Enter to send, Shift+Enter for newline)"
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy || !connected}
          />
          {busy && !cancelling && (
            <button css={cancelButtonCss} onClick={cancelTurn}>Cancel</button>
          )}
          {busy && cancelling && (
            <span css={cancellingLabelCss}>cancelling turn...</span>
          )}
          <button css={sendButtonCss} onClick={send} disabled={busy || !connected}>
            <span css={busy ? css`visibility: hidden` : undefined}>Send</span>
            {busy && <span css={spinnerCss} />}
          </button>
        </div>
      </div>
    </div>
  )
}
