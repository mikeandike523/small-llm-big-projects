/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useEffect, useState, useCallback } from 'react'
import { socket } from '../socket'
import { useScrollToBottom } from '../hooks/useScrollToBottom'
import { TextPresenter } from './TextPresenter'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
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
}

interface Turn {
  id: string
  user: UserEntry
  assistant: AssistantEntry
}

function makeId() {
  return Math.random().toString(36).slice(2)
}

function newAssistant(streaming = true): AssistantEntry {
  return { type: 'assistant', id: makeId(), reasoning: '', content: '', toolCalls: [], streaming }
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const rootCss = css`
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 1600px;
  width: 96%;
  margin: 0 auto;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 15px;
  background: #0f0f0f;
  color: #e0e0e0;
`

const threadCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 0;
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
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 20px;
  font-size: 14px;
  cursor: pointer;
  align-self: flex-end;
  height: 40px;
  &:disabled {
    background: #1e3a6e;
    cursor: not-allowed;
  }
`

const userBubbleCss = css`
  background: #1d4ed8;
  border-radius: 16px 16px 4px 16px;
  padding: 10px 14px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  align-self: flex-end;
`

const assistantBubbleCss = css`
  background: #1e1e1e;
  border-radius: 16px 16px 16px 4px;
  padding: 10px 14px;
  word-break: break-word;
  line-height: 1.5;
`

const streamingPlaceholderCss = css`
  background: #1e1e1e;
  border-radius: 16px 16px 16px 4px;
  padding: 10px 14px;
  color: #555;
`

const reasoningWrapperCss = css`
  color: #7aa2e0;
  font-size: 13px;
  font-style: italic;
`

const toolCallCss = css`
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
  font-size: 13px;
`

const toolHeaderCss = css`
  background: #2a1a4a;
  color: #b48be0;
  padding: 6px 12px;
  font-family: 'Consolas', monospace;
`

const toolArgsCss = css`
  background: #1a1a2e;
  color: #a0a0c0;
  padding: 6px 12px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 160px;
  overflow-y: auto;
`

const toolResultCss = css`
  background: #0d1f0d;
  color: #7ec87e;
  padding: 6px 12px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #1a3a1a;
  max-height: 220px;
  overflow-y: auto;
`

const statusCss = css`
  font-size: 12px;
  color: #555;
  padding: 4px 16px;
  text-align: center;
`

const turnContainerCss = css`
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 20px;
  padding: 20px 0;
  border-bottom: 1px solid #1a1a1a;
`

const leftColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 12px;
`

const rightColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 10px;
`

const toolCallsGroupCss = css`
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
`

// ---------------------------------------------------------------------------
// TurnContainer
// ---------------------------------------------------------------------------

function TurnContainer({ turn }: { turn: Turn }) {
  const { user, assistant } = turn
  return (
    <div css={turnContainerCss}>
      {/* Left column: user message + AI content */}
      <div css={leftColumnCss}>
        <div css={userBubbleCss}>{user.text}</div>
        {assistant.content ? (
          <div css={assistantBubbleCss}>
            <TextPresenter
              content={assistant.content}
              maxHeight={600}
              streaming={assistant.streaming}
            />
          </div>
        ) : null}
        {assistant.streaming && !assistant.content && assistant.toolCalls.length === 0 && (
          <div css={streamingPlaceholderCss}>…</div>
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
          <div css={toolCallsGroupCss}>
            {assistant.toolCalls.map(tc => (
              <div key={tc.id} css={toolCallCss}>
                <div css={toolHeaderCss}>⚙ {tc.name}</div>
                {Object.keys(tc.args).length > 0 && (
                  <div css={toolArgsCss}>{JSON.stringify(tc.args, null, 2)}</div>
                )}
                {tc.result !== undefined && (
                  <div css={toolResultCss}>{tc.result}</div>
                )}
              </div>
            ))}
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
    function onConnect() { setConnected(true) }
    function onDisconnect() { setConnected(false) }

    function onToken({ type, text }: { type: 'reasoning' | 'content'; text: string }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        const a = last.assistant
        if (!a.streaming) return prev
        const updated: AssistantEntry = {
          ...a,
          reasoning: type === 'reasoning' ? a.reasoning + text : a.reasoning,
          content:   type === 'content'   ? a.content   + text : a.content,
        }
        return [...prev.slice(0, -1), { ...last, assistant: updated }]
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

    function onMessageDone({ content }: { content: string }) {
      setThread(prev => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, assistant: { ...last.assistant, content, streaming: false } }]
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

    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    socket.on('token', onToken)
    socket.on('tool_call', onToolCall)
    socket.on('tool_result', onToolResult)
    socket.on('message_done', onMessageDone)
    socket.on('error', onError)

    return () => {
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
      socket.off('token', onToken)
      socket.off('tool_call', onToolCall)
      socket.off('tool_result', onToolResult)
      socket.off('message_done', onMessageDone)
      socket.off('error', onError)
    }
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
      <div css={statusCss}>
        {connected ? '● connected' : '○ disconnected'}
      </div>
      <div css={threadCss} ref={threadRef} onScroll={handleScroll}>
        {thread.map(turn => <TurnContainer key={turn.id} turn={turn} />)}
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
          Send
        </button>
      </div>
    </div>
  )
}
