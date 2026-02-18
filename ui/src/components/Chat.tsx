/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useEffect, useRef, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { socket } from '../socket'

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

type ThreadEntry = UserEntry | AssistantEntry

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
  max-width: 820px;
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

const bubbleCss = (role: 'user' | 'assistant') => css`
  display: flex;
  flex-direction: column;
  align-items: ${role === 'user' ? 'flex-end' : 'flex-start'};
`

const userBubbleCss = css`
  max-width: 78%;
  background: #1d4ed8;
  border-radius: 16px 16px 4px 16px;
  padding: 10px 14px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
`

const assistantBubbleCss = css`
  max-width: 78%;
  background: #1e1e1e;
  border-radius: 16px 16px 16px 4px;
  padding: 10px 14px;
  word-break: break-word;
  line-height: 1.5;

  p { margin: 0.4em 0; }
  p:first-child { margin-top: 0; }
  p:last-child { margin-bottom: 0; }

  h1, h2, h3, h4, h5, h6 { margin: 0.6em 0 0.3em; font-weight: 600; line-height: 1.3; }
  h1 { font-size: 1.4em; }
  h2 { font-size: 1.25em; }
  h3 { font-size: 1.1em; }

  ul, ol { padding-left: 1.5em; margin: 0.4em 0; }
  li { margin: 0.2em 0; }

  blockquote {
    border-left: 3px solid #444;
    padding-left: 0.8em;
    color: #aaa;
    margin: 0.4em 0;
    font-style: italic;
  }

  code {
    background: #2a2a2a;
    padding: 0.15em 0.35em;
    border-radius: 4px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 0.9em;
  }

  pre {
    background: #141414;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 10px 12px;
    overflow-x: auto;
    margin: 0.5em 0;
  }

  pre code {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 0.85em;
    line-height: 1.5;
  }

  a { color: #7aa2e0; text-decoration: none; }
  a:hover { text-decoration: underline; }

  hr { border: none; border-top: 1px solid #333; margin: 0.6em 0; }

  table { border-collapse: collapse; width: 100%; margin: 0.5em 0; font-size: 0.9em; }
  th { background: #252525; padding: 6px 10px; text-align: left; border: 1px solid #333; }
  td { padding: 5px 10px; border: 1px solid #2a2a2a; }
  tr:nth-child(even) td { background: #1a1a1a; }

  .hljs { background: transparent !important; }
`

const streamingPlaceholderCss = css`
  max-width: 78%;
  background: #1e1e1e;
  border-radius: 16px 16px 16px 4px;
  padding: 10px 14px;
  color: #555;
`

const reasoningCss = css`
  color: #7aa2e0;
  font-size: 13px;
  font-style: italic;
  margin-bottom: 6px;
  white-space: pre-wrap;
  word-break: break-word;
`

const toolCallCss = css`
  margin-top: 8px;
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
  font-size: 13px;
  max-width: 78%;
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
`

const toolResultCss = css`
  background: #0d1f0d;
  color: #7ec87e;
  padding: 6px 12px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #1a3a1a;
`

const statusCss = css`
  font-size: 12px;
  color: #555;
  padding: 4px 16px;
  text-align: center;
`

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Chat() {
  const [thread, setThread] = useState<ThreadEntry[]>([])
  const [inputText, setInputText] = useState('')
  const [connected, setConnected] = useState(socket.connected)
  const [busy, setBusy] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom whenever thread updates
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [thread])

  // ---------------------------------------------------------------------------
  // Socket wiring
  // ---------------------------------------------------------------------------

  useEffect(() => {
    function onConnect() { setConnected(true) }
    function onDisconnect() { setConnected(false) }

    function onToken({ type, text }: { type: 'reasoning' | 'content'; text: string }) {
      setThread(prev => {
        const last = prev[prev.length - 1]
        if (last?.type === 'assistant' && last.streaming) {
          const updated: AssistantEntry = {
            ...last,
            reasoning: type === 'reasoning' ? last.reasoning + text : last.reasoning,
            content:   type === 'content'   ? last.content   + text : last.content,
          }
          return [...prev.slice(0, -1), updated]
        }
        // No current assistant bubble — create one
        const entry = newAssistant(true)
        return [
          ...prev,
          {
            ...entry,
            reasoning: type === 'reasoning' ? text : '',
            content:   type === 'content'   ? text : '',
          },
        ]
      })
    }

    function onToolCall({ id, name, args }: { id: string; name: string; args: Record<string, unknown> }) {
      setThread(prev => {
        const last = prev[prev.length - 1]
        if (last?.type === 'assistant') {
          const updated: AssistantEntry = {
            ...last,
            toolCalls: [...last.toolCalls, { id, name, args }],
          }
          return [...prev.slice(0, -1), updated]
        }
        // No assistant bubble yet — create one then add the tool call
        const entry = newAssistant(true)
        return [...prev, { ...entry, toolCalls: [{ id, name, args }] }]
      })
    }

    function onToolResult({ id, result }: { id: string; result: string }) {
      setThread(prev => {
        const last = prev[prev.length - 1]
        if (last?.type === 'assistant') {
          const updated: AssistantEntry = {
            ...last,
            toolCalls: last.toolCalls.map(tc =>
              tc.id === id ? { ...tc, result } : tc
            ),
          }
          return [...prev.slice(0, -1), updated]
        }
        return prev
      })
    }

    function onMessageDone({ content }: { content: string }) {
      setThread(prev => {
        const last = prev[prev.length - 1]
        if (last?.type === 'assistant') {
          return [...prev.slice(0, -1), { ...last, content, streaming: false }]
        }
        return [...prev, { ...newAssistant(false), content }]
      })
      setBusy(false)
    }

    function onError({ message }: { message: string }) {
      setThread(prev => [
        ...prev,
        { type: 'assistant', id: makeId(), reasoning: '', content: `⚠ ${message}`, toolCalls: [], streaming: false },
      ])
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

    setThread(prev => [...prev, { type: 'user', id: makeId(), text }])
    setThread(prev => [...prev, newAssistant(true)])
    setBusy(true)
    setInputText('')

    socket.emit('user_message', { text })
  }, [inputText, busy, connected])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderEntry(entry: ThreadEntry) {
    if (entry.type === 'user') {
      return (
        <div key={entry.id} css={bubbleCss('user')}>
          <div css={userBubbleCss}>{entry.text}</div>
        </div>
      )
    }

    return (
      <div key={entry.id} css={bubbleCss('assistant')}>
        {entry.reasoning ? (
          <div css={reasoningCss}>{entry.reasoning}</div>
        ) : null}
        {entry.content ? (
          <div css={assistantBubbleCss}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
            >
              {entry.content}
            </ReactMarkdown>
          </div>
        ) : null}
        {entry.toolCalls.map(tc => (
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
        {entry.streaming && !entry.content && entry.toolCalls.length === 0 && (
          <div css={streamingPlaceholderCss}>…</div>
        )}
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div css={rootCss}>
      <div css={statusCss}>
        {connected ? '● connected' : '○ disconnected'}
      </div>
      <div css={threadCss}>
        {thread.map(renderEntry)}
        <div ref={bottomRef} />
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
