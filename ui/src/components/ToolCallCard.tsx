import { css, keyframes } from '@emotion/react'

import { ToolCallEntry } from '../types';
import ElapsedTimer from './ElapsedTimer';
import JsonArgsViewer from './JsonArgsViewer';
import Ansi from 'ansi-to-react';
import { MAX_TOOL_CHARS } from '../constants/tool-ui-constants';
import { toolArgsCss, toolCallCss, toolHeaderCss, toolResultCss, viewFullButtonCss } from '../css/tool-ui-css';


const MAX_STREAMING_CHARS = 300






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






const deniedToolResultCss = css`
  background: #1a0505;
  color: #f87171;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #5a1a1a;
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

export default function ToolCallCard({ tc, onViewFull }: { tc: ToolCallEntry; onViewFull: (c: string) => void }) {
  const hasResult = tc.result !== undefined
  const isStreaming = !hasResult && tc.streamingResult !== undefined
  const truncated = hasResult && tc.result!.length > MAX_TOOL_CHARS
  const isDenied = hasResult && tc.result!.startsWith('Error: NOT Approved.')

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
        <div css={toolArgsCss}><JsonArgsViewer args={tc.args} /></div>
      )}
      {isStreaming && displayResult !== undefined && (
        <div css={streamingResultCss}><Ansi>{displayResult}</Ansi></div>
      )}
      {hasResult && (
        <div css={isDenied ? deniedToolResultCss : toolResultCss}><Ansi>{displayResult}</Ansi></div>
      )}
    </div>
  )
}