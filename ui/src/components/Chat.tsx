/** @jsxImportSource @emotion/react */
import { css, keyframes } from '@emotion/react'
import { useEffect, useState, useCallback } from 'react'
import { socket } from '../socket'
import { useScrollToBottom } from '../hooks/useScrollToBottom'
import { TextPresenter } from './TextPresenter'
import Ansi from 'ansi-to-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TOOL_CHARS = 80

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
// Types
// ---------------------------------------------------------------------------

interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
}

interface TodoItem {
  item_number: number
  text: string
  status: 'open' | 'closed'
}

interface ApprovalItem {
  id: string
  tool_name: string
  args: Record<string, unknown>
  resolved?: { approved: boolean }
}

interface UserEntry {
  type: 'user'
  id: string
  text: string
}

interface AssistantEntry {
  type: 'assistant'
  id: string
  reasoning: string
  content: string
  toolCalls: ToolCallEntry[]
  streaming: boolean
  interimCharCount: number
  isInterimStreaming: boolean
}

interface Turn {
  id: string
  user: UserEntry
  assistant: AssistantEntry
  todoItems: TodoItem[]
  approvalItem?: ApprovalItem
  impossible?: string
}

function makeId() {
  return Math.random().toString(36).slice(2)
}

function newAssistant(streaming = true): AssistantEntry {
  return { type: 'assistant', id: makeId(), reasoning: '', content: '', toolCalls: [], streaming, interimCharCount: 0, isInterimStreaming: false }
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const rootCss = css`
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 1800px;
  width: 96%;
  margin: 0 auto;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 15px;
  background: #0f0f0f;
  color: #e0e0e0;
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

// User bubble — constrained + auto-scroll (one of the 4 regions)
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

// Assistant bubble — wraps TextPresenter which handles its own scroll (one of the 4 regions)
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

// Impossible bubble — shown below assistant content
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

// Reasoning wrapper — wraps TextPresenter which handles its own scroll (one of the 4 regions)
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

// Individual tool call card — NO scroll, NO max-height; fixed height by design (truncated result)
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

// Args — no max-height, no scroll; typically short JSON
const toolArgsCss = css`
  background: #16162a;
  color: #a0a0c0;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #252545;
`

// Result — no max-height, no scroll; content is truncated to MAX_TOOL_CHARS
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

// Tool calls GROUP — constrained + auto-scroll (one of the 4 regions)
const toolCallsGroupCss = css`
  ${scrollbarCss}
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
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
  color: #555;
  white-space: nowrap;
`

const pwdCss = css`
  font-size: 11px;
  color: #383838;
  font-family: 'Consolas', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70%;
  text-align: right;
`

// TurnContainer — UNCONSTRAINED; grows to fit all child regions
const turnContainerCss = css`
  display: grid;
  grid-template-columns: 3fr 2fr 1.5fr 1.5fr;
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

// ---------------------------------------------------------------------------
// Todo column styles
// ---------------------------------------------------------------------------

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

const todoItemOpenCss = css`
  font-size: 12px;
  color: #c0c0c0;
  font-family: 'Consolas', monospace;
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`

const todoItemClosedCss = css`
  font-size: 12px;
  color: #505050;
  font-family: 'Consolas', monospace;
  padding: 2px 0;
  text-decoration: line-through;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`

const todoEmptyCss = css`
  font-size: 12px;
  color: #3a3a3a;
  font-style: italic;
`

// ---------------------------------------------------------------------------
// Approval column styles
// ---------------------------------------------------------------------------

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

const approvalResolvedCss = (approved: boolean) => css`
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: ${approved ? '#4ade80' : '#f87171'};
  padding: 4px 0;
  word-break: break-all;
`

// ---------------------------------------------------------------------------
// Modal styles
// ---------------------------------------------------------------------------

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
  const { user, assistant, todoItems, approvalItem, impossible } = turn
  const { containerRef: toolsRef, scrollToBottomIfNeeded: scrollTools, onScroll: onToolsScroll } =
    useScrollToBottom<HTMLDivElement>()

  useEffect(() => {
    if (assistant.streaming) scrollTools()
  }, [assistant.toolCalls, assistant.streaming, scrollTools])

  return (
    <div css={turnContainerCss}>
      {/* Left column: user message + AI content + impossible notice */}
      <div css={leftColumnCss}>
        <div css={userBubbleCss}>{user.text}</div>
        {(assistant.interimCharCount > 0 || assistant.isInterimStreaming) && (
          <div css={interimBubbleCss}>
            AI interim response: {assistant.interimCharCount} chars
          </div>
        )}
        {assistant.content ? (
          <div css={assistantBubbleCss}>
            <TextPresenter
              content={assistant.content}
              maxHeight={600}
              streaming={assistant.streaming}
            />
          </div>
        ) : null}
        {assistant.streaming && !assistant.content && !assistant.isInterimStreaming && assistant.toolCalls.length === 0 && (
          <div css={streamingPlaceholderCss}>…</div>
        )}
        {impossible && (
          <div css={impossibleBubbleCss}>
            <span css={impossibleLabelCss}>Task impossible</span>
            <span css={impossibleReasonCss}>{impossible}</span>
          </div>
        )}
      </div>

      {/* Right column: reasoning + tool calls */}
      <div css={rightColumnCss}>
        {assistant.reasoning ? (
          <div css={reasoningWrapperCss}>
            <TextPresenter
              content={assistant.reasoning}
              maxHeight={200}
              streaming={assistant.streaming}
              initialMode="plain"
              showToggle={false}
            />
          </div>
        ) : null}
        {assistant.toolCalls.length > 0 && (
          <div css={toolCallsGroupCss} ref={toolsRef} onScroll={onToolsScroll}>
            {assistant.toolCalls.map(tc => {
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
        )}
      </div>

      {/* Third column: todo list */}
      <div css={todoColumnCss}>
        <div css={todoHeaderCss}>Todo</div>
        {todoItems.length === 0
          ? <div css={todoEmptyCss}>empty</div>
          : todoItems.map(item => (
              <div
                key={item.item_number}
                css={item.status === 'closed' ? todoItemClosedCss : todoItemOpenCss}
                title={item.text}
              >
                {item.item_number}. {item.text}
              </div>
            ))
        }
      </div>

      {/* Fourth column: approval */}
      <div css={approvalColumnCss}>
        <div css={approvalHeaderCss}>Approval</div>
        {!approvalItem ? (
          <div css={approvalEmptyCss}>—</div>
        ) : approvalItem.resolved ? (
          <div css={approvalResolvedCss(approvalItem.resolved.approved)}>
            {approvalItem.resolved.approved ? '✓' : '✗'} {approvalItem.tool_name}
          </div>
        ) : (
          <div css={approvalPendingCardCss}>
            <div css={approvalToolNameCss}>{approvalItem.tool_name}</div>
            {Object.keys(approvalItem.args).length > 0 && (
              <div css={approvalArgsCss}>{JSON.stringify(approvalItem.args, null, 2)}</div>
            )}
            <div css={approvalButtonRowCss}>
              <button css={approveButtonCss} onClick={() => onApprove(approvalItem.id)}>
                Approve
              </button>
              <button css={denyButtonCss} onClick={() => onDeny(approvalItem.id)}>
                Deny
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Chat() {
  const [thread, setThread] = useState<Turn[]>([])
  const [inputText, setInputText] = useState('')
  const [connected, setConnected] = useState(socket.connected)
  const [busy, setBusy] = useState(false)
  const [modalContent, setModalContent] = useState<string | null>(null)
  const [pwd, setPwd] = useState<string>('')

  const {
    containerRef: threadRef,
    isAtBottom,
    scrollToBottomIfNeeded,
    onScroll: handleScroll,
  } = useScrollToBottom<HTMLDivElement>()

  // Scroll to bottom on thread updates only when already at the bottom.
  useEffect(() => {
    scrollToBottomIfNeeded()
  }, [thread, scrollToBottomIfNeeded])

  // ---------------------------------------------------------------------------
  // Socket wiring
  // ---------------------------------------------------------------------------

  useEffect(() => {
    // Fetch current pwd immediately if already connected at mount time.
    if (socket.connected) socket.emit('get_pwd')

    function onConnect() {
      setConnected(true)
      socket.emit('get_pwd')
    }
    function onDisconnect() { setConnected(false) }
    function onPwdUpdate({ path }: { path: string }) { setPwd(path) }

    function onToken({ type, text }: { type: 'reasoning' | 'content'; text: string }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        const a = last.assistant
        if (!a.streaming) return prev
        if (a.isInterimStreaming && type === 'content') {
          return [...prev.slice(0, -1), { ...last, assistant: { ...a, interimCharCount: a.interimCharCount + text.length } }]
        }
        const updated: AssistantEntry = {
          ...a,
          reasoning: type === 'reasoning' ? a.reasoning + text : a.reasoning,
          content:   type === 'content'   ? a.content   + text : a.content,
        }
        return [...prev.slice(0, -1), { ...last, assistant: updated }]
      })
    }

    function onBeginInterimStream() {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, assistant: { ...last.assistant, isInterimStreaming: true } }]
      })
    }

    function onBeginFinalSummary() {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, assistant: { ...last.assistant, isInterimStreaming: false } }]
      })
    }

    function onToolCall({ id, name, args }: { id: string; name: string; args: Record<string, unknown> }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        const a = last.assistant
        const updated: AssistantEntry = {
          ...a,
          toolCalls: [...a.toolCalls, { id, name, args }],
        }
        return [...prev.slice(0, -1), { ...last, assistant: updated }]
      })
    }

    function onToolResult({ id, result }: { id: string; result: string }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        const a = last.assistant
        const updated: AssistantEntry = {
          ...a,
          toolCalls: a.toolCalls.map(tc => tc.id === id ? { ...tc, result } : tc),
        }
        return [...prev.slice(0, -1), { ...last, assistant: updated }]
      })
    }

    function onMessageDone({ content }: { content: string | null }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        const updatedAssistant: AssistantEntry = {
          ...last.assistant,
          streaming: false,
          ...(content !== null ? { content } : {}),
        }
        return [...prev.slice(0, -1), { ...last, assistant: updatedAssistant }]
      })
      setBusy(false)
    }

    function onError({ message }: { message: string }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), {
          ...last,
          assistant: { ...last.assistant, content: `⚠ ${message}`, streaming: false },
        }]
      })
      setBusy(false)
    }

    function onReportImpossible({ reason }: { reason: string }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, impossible: reason }]
      })
      // busy is cleared by the subsequent message_done event
    }

    function onTodoListUpdate({ items }: { items: TodoItem[] }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, todoItems: items }]
      })
    }

    function onApprovalRequest({ id, tool_name, args }: { id: string; tool_name: string; args: Record<string, unknown> }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, approvalItem: { id, tool_name, args } }]
      })
    }

    function onApprovalResolved({ id, approved }: { id: string; approved: boolean }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        if (!last.approvalItem || last.approvalItem.id !== id) return prev
        return [...prev.slice(0, -1), {
          ...last,
          approvalItem: { ...last.approvalItem, resolved: { approved } },
        }]
      })
    }

    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    socket.on('pwd_update', onPwdUpdate)
    socket.on('token', onToken)
    socket.on('begin_interim_stream', onBeginInterimStream)
    socket.on('begin_final_summary', onBeginFinalSummary)
    socket.on('tool_call', onToolCall)
    socket.on('tool_result', onToolResult)
    socket.on('message_done', onMessageDone)
    socket.on('error', onError)
    socket.on('report_impossible', onReportImpossible)
    socket.on('todo_list_update', onTodoListUpdate)
    socket.on('approval_request', onApprovalRequest)
    socket.on('approval_resolved', onApprovalResolved)

    return () => {
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
      socket.off('pwd_update', onPwdUpdate)
      socket.off('token', onToken)
      socket.off('begin_interim_stream', onBeginInterimStream)
      socket.off('begin_final_summary', onBeginFinalSummary)
      socket.off('tool_call', onToolCall)
      socket.off('tool_result', onToolResult)
      socket.off('message_done', onMessageDone)
      socket.off('error', onError)
      socket.off('report_impossible', onReportImpossible)
      socket.off('todo_list_update', onTodoListUpdate)
      socket.off('approval_request', onApprovalRequest)
      socket.off('approval_resolved', onApprovalResolved)
    }
  }, [])

  // ---------------------------------------------------------------------------
  // Approval actions
  // ---------------------------------------------------------------------------

  const approve = useCallback((id: string) => {
    socket.emit('approval_response', { id, approved: true })
  }, [])

  const deny = useCallback((id: string) => {
    socket.emit('approval_response', { id, approved: false })
  }, [])

  // ---------------------------------------------------------------------------
  // Send
  // ---------------------------------------------------------------------------

  const send = useCallback(() => {
    const text = inputText.trim()
    if (!text || busy || !connected) return

    setThread(prev => [...prev, {
      id: makeId(),
      user: { type: 'user', id: makeId(), text },
      assistant: newAssistant(true),
      todoItems: [],
    }])
    setBusy(true)
    setInputText('')

    // Re-enable autoscroll so the incoming response is followed.
    isAtBottom.current = true
    socket.emit('user_message', { text })
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
    <div css={rootCss}>
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
        {pwd && <span css={pwdCss}>{pwd}</span>}
      </div>
      <div css={threadCss} ref={threadRef} onScroll={handleScroll}>
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
        <button css={sendButtonCss} onClick={send} disabled={busy || !connected}>
          <span css={busy ? css`visibility: hidden` : undefined}>Send</span>
          {busy && <span css={spinnerCss} />}
        </button>
      </div>
    </div>
  )
}
