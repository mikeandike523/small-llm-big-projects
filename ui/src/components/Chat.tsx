/** @jsxImportSource @emotion/react */
import React from 'react'
import { css, keyframes } from '@emotion/react'
import { useEffect, useRef, useState, useCallback } from 'react'
import { type Socket } from 'socket.io-client'
import { useNavigate } from 'react-router-dom'
import { createSocket } from '../socket'
import { useStickToBottom } from 'use-stick-to-bottom'
import { TextPresenter } from './TextPresenter'
import { DebugPanel } from './DebugPanel'
import Ansi from 'ansi-to-react'
import type { Turn, Subturn, ToolCallEntry, TodoItem, ApprovalItem } from '../types'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TOOL_CHARS = 80
const MAX_LOGS = 100
const JSON_VALUE_MAX_LINES = 10

function formatCost(usd: number): string {
  if (usd < 0.001) return usd.toFixed(6)
  if (usd < 0.1) return usd.toFixed(4)
  return usd.toFixed(2)
}


// ---------------------------------------------------------------------------
// Shared scrollbar styles
// ---------------------------------------------------------------------------

const scrollbarCss = css`
  &::-webkit-scrollbar { width: 6px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #2f4f86; border-radius: 3px; }
  &::-webkit-scrollbar-thumb:hover { background: #4f73b3; }
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

function newTurn(id: string, userText: string, subturnId?: string): Turn {
  const stId = subturnId ?? crypto.randomUUID()
  return {
    id,
    subturns: [{ id: stId, userText, exchanges: [] }],
    todoItems: [],
    approvalItems: [],
    completed: false,
    streaming: true,
    isInterimStreaming: false,
    interimShowCharCount: false,
    interimCharCount: 0,
  }
}

function emptyExchange() {
  return { assistantContent: '', reasoning: '', iratThinking: '', toolCalls: [], isFinal: false as const }
}

function stripMdExtension(s: string): string {
  return s.endsWith('.md') ? s.slice(0, -3) : s
}

type BackendExchange = {
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
}

type BackendSubturn = {
  id: string
  user_text: string
  exchanges: BackendExchange[]
  detailed_summary?: string
}

function mapExchange(ex: BackendExchange) {
  return {
    assistantContent: ex.assistant_content,
    reasoning: ex.reasoning,
    iratThinking: '',
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
  }
}

function backendTurnToFrontendTurn(d: {
  id: string
  subturns?: BackendSubturn[]
  // legacy format (schema v3 and below)
  user_text?: string
  exchanges?: BackendExchange[]
  task_title?: string
  todo_snapshot: TodoItem[]
  was_impossible?: boolean
  impossible_reason?: string
  completed: boolean
}): Turn {
  const subturns: Subturn[] = d.subturns && d.subturns.length > 0
    ? d.subturns.map(st => ({
        id: st.id,
        userText: st.user_text,
        exchanges: st.exchanges.map(mapExchange),
        detailedSummary: st.detailed_summary ?? undefined,
      }))
    : [{
        id: crypto.randomUUID(),
        userText: d.user_text ?? '',
        exchanges: (d.exchanges ?? []).map(mapExchange),
      }]

  return {
    id: d.id,
    taskTitle: d.task_title ?? undefined,
    subturns,
    todoItems: d.todo_snapshot ?? [],
    approvalItems: [],
    impossible: d.was_impossible ? (d.impossible_reason ?? 'Task was impossible') : undefined,
    completed: d.completed,
    streaming: false,
    isInterimStreaming: false,
    interimShowCharCount: false,
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
  gap: 28px;
`

const inputBarCss = css`
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #22304d;
  background: #101722;
`

const textareaCss = css`
  flex: 1;
  background: #101722;
  color: #f3f6ff;
  border: 1px solid #30405f;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
  &:focus {
    border-color: #8aa4d8;
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

const stopButtonCss = css`
  background: #1a0a0a;
  color: #c06060;
  border: 1px solid #4a1818;
  border-radius: 8px;
  padding: 0 16px;
  font-size: 14px;
  cursor: pointer;
  font-family: inherit;
  height: 40px;
  align-self: flex-end;
  transition: background 0.15s, border-color 0.15s;
  &:hover { background: #2a1010; border-color: #6a2424; }
  &:disabled { opacity: 0.4; cursor: not-allowed; }
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
  background: #111827;
  border: 1px solid #283754;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  word-break: break-word;
  line-height: 1.5;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
`

const streamingPlaceholderCss = css`
  background: #111827;
  border: 1px solid #283754;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  color: #dbe5ff;
`

const interimBubbleCss = css`
  background: #0f1726;
  border: 1px solid #24324d;
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 11px;
  color: #d6e0f5;
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
  color: #d5b8ff;
  font-style: italic;
`

// Mini compaction bubble (appears below assistant response when detailed_summary is available)
const compactionBubbleCss = css`
  background: #1a0815;
  border: 1px solid #7a2545;
  border-radius: 10px;
  padding: 8px 12px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 4px;
`

const compactionTextCss = css`
  font-size: 11px;
  color: #c87090;
  flex: 1;
  font-style: italic;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
`

const compactionDetailsButtonCss = css`
  background: none;
  border: 1px solid #7a2545;
  border-radius: 4px;
  color: #c87090;
  font-size: 10px;
  padding: 2px 6px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  &:hover { background: #2a0d20; }
`

// Compaction detail modal
const compactionModalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`

const compactionModalCss = css`
  background: #0e0e14;
  border: 1px solid #7a2545;
  border-radius: 12px;
  padding: 20px 24px;
  max-width: 680px;
  width: 90%;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  gap: 12px;
`

const compactionModalTitleCss = css`
  font-size: 13px;
  font-weight: 600;
  color: #c87090;
`

const compactionModalBodyCss = css`
  font-size: 12px;
  color: #d4a8b8;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
  flex: 1;
  line-height: 1.6;
`

const compactionModalCloseCss = css`
  background: #2a0d20;
  border: 1px solid #7a2545;
  border-radius: 6px;
  color: #c87090;
  font-size: 12px;
  padding: 6px 14px;
  cursor: pointer;
  align-self: flex-end;
  &:hover { background: #3a1030; }
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

const iratThinkingWrapperCss = css`
  color: #c49a4a;
  font-size: 13px;
  font-style: italic;
  background: #1a1408;
  border: 1px solid #4a360f;
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
  padding: 8px 14px;
  border-top: 1px solid #252545;
`

const jsonRowCss = css`
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  margin-bottom: 2px;
`

const jsonKeyCss = css`
  color: #6b9fe4;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
`

const jsonValueCss = css`
  background: #202030;
  color: #b8bfd8;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  padding: 0px 5px;
  border-radius: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  flex: 1;
  min-width: 0;
`

const jsonValueScrollableCss = css`
  background: #202030;
  color: #b8bfd8;
  font-family: 'Consolas', monospace;
  font-size: 11px;
  padding: 2px 5px;
  border-radius: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  width: 100%;
  box-sizing: border-box;
  max-height: ${JSON_VALUE_MAX_LINES}em;
  overflow-y: auto;
  display: block;
  ${scrollbarCss}
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

const deniedToolResultCss = css`
  background: #1a0505;
  color: #f87171;
  padding: 8px 14px;
  font-family: 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #5a1a1a;
`

const toolCallsGroupCss = css`
  ${scrollbarCss}
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
`

const subturnDividerCss = css`
  font-size: 10px;
  color: #3a4d6e;
  text-align: center;
  padding: 2px 0;
  border-top: 1px solid #1e2d45;
  margin: 2px 0;
  letter-spacing: 0.04em;
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
  color: #dbf0db;
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
  padding: 8px 16px;
  border-bottom: 1px solid #1d2940;
  flex-shrink: 0;
  gap: 12px;
`

const headerSideCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
`

const sessionCostCss = css`
  font-size: 10px;
  color: #6a9060;
  font-family: 'Consolas', monospace;
  white-space: nowrap;
`

const statusCss = css`
  font-size: 11px;
  color: #f2f6ff;
  font-family: 'Consolas', monospace;
  white-space: nowrap;
`

const sessionIdCss = css`
  font-size: 10px;
  color: #dbe5ff;
  font-family: 'Consolas', monospace;
  white-space: nowrap;
  cursor: default;
`

const dashboardButtonCss = css`
  background: #101722;
  color: #f3f6ff;
  border: 1px solid #30405f;
  border-radius: 999px;
  width: 28px;
  height: 28px;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
  &:hover {
    background: #172235;
    border-color: #6f8fc5;
    transform: translateX(-1px);
  }
`

const turnWrapperCss = css`
  display: flex;
  flex-direction: column;
  gap: 0;
`

const turnBannerCss = css`
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-family: 'Consolas', monospace;
  background: #0d180d;
  border: 1px solid #1e3a1e;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  padding: 5px 16px;
`

const taskTitleCss = css`
  font-size: 11px;
  color: #6a9a6a;
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 1;
`

const skillPillsRowCss = css`
  display: flex;
  gap: 5px;
  flex-shrink: 0;
  align-items: center;
`

const skillPillCss = css`
  font-size: 10px;
  color: #5090c0;
  background: #0d1a2d;
  border: 1px solid #1e3a5a;
  border-radius: 10px;
  padding: 2px 8px;
  letter-spacing: 0.03em;
  white-space: nowrap;
`

const turnContainerCss = css`
  display: grid;
  grid-template-columns: 3fr 2fr 2fr auto;
  gap: 24px;
  padding: 20px 24px;
  border: 1px solid #22304d;
  border-radius: 0 0 12px 12px;
  background: #0d131e;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
`

const turnContainerNoTitleCss = css`
  display: grid;
  grid-template-columns: 3fr 2fr 2fr auto;
  gap: 24px;
  padding: 20px 24px;
  border: 1px solid #22304d;
  border-radius: 12px;
  background: #0d131e;
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
  border-left: 1px solid #22304d;
  padding-left: 16px;
  min-width: 0;
`

const todoHeaderCss = css`
  font-size: 11px;
  color: #e6edff;
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
  color: #dbe5ff;
  font-style: italic;
`

const approvalRowCss = css`
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid #22304d;
  padding-top: 16px;
  min-height: 120px;
`

// Inner 3-column grid for the approval/questions row
const approvalInnerGridCss = css`
  display: grid;
  grid-template-columns: 150px 1.2fr 1fr;
  min-height: 100px;
`

// Base for each column inside the grid
const approvalCol1Css = css`
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 14px 4px 2px;
  min-width: 0;
  min-height: 0;
`

const approvalCol2Css = css`
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 14px 4px 14px;
  border-left: 1px solid #22304d;
  min-width: 0;
`

const approvalCol3Css = css`
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0 4px 4px 14px;
  border-left: 1px solid #22304d;
  min-width: 0;
  min-height: 0;
`

const approvalColHeaderCss = css`
  font-size: 10px;
  color: #e6edff;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-family: 'Consolas', monospace;
  margin-bottom: 4px;
  flex-shrink: 0;
`

const _approvalColHeaderPulse = keyframes`
  0%, 100% { color: #a07030; }
  50%       { color: #d4a030; }
`

const approvalColHeaderPendingCss = css`
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-family: 'Consolas', monospace;
  margin-bottom: 4px;
  flex-shrink: 0;
  font-weight: 600;
  animation: ${_approvalColHeaderPulse} 1.8s ease-in-out infinite;
`

// Col 1: outcome chips
const outcomesScrollCss = css`
  ${scrollbarCss}
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  max-height: 200px;
  padding-right: 4px;
`

const approvalListContentCss = (gap: number) => css`
  display: flex;
  flex-direction: column;
  gap: ${gap}px;
`

const outcomeApprovalChipCss = (approved: boolean) => css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: ${approved ? '#4ade80' : '#f87171'};
  background: ${approved ? '#071207' : '#120707'};
  border: 1px solid ${approved ? '#14532d' : '#450a0a'};
  border-radius: 3px;
  padding: 2px 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`

// Col 2: active dialog placeholder (nothing pending)
const activeDialogPlaceholderCss = css`
  font-size: 12px;
  color: #dbe5ff;
  font-style: italic;
  font-family: 'Consolas', monospace;
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
  margin-bottom: 4px;
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

const denyRedirectButtonCss = css`
  flex: 1;
  background: #78350f;
  color: #fbbf24;
  border: 1px solid #92400e;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  transition: background 0.15s;
  &:hover { background: #92400e; }
`

const denyAndStopButtonCss = css`
  flex: 1;
  background: #3b0a0a;
  color: #fca5a5;
  border: 1px solid #991b1b;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  transition: background 0.15s;
  &:hover { background: #7f1d1d; }
`

const redirectInputAreaCss = css`
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 6px;
`

const redirectTextareaCss = css`
  width: 100%;
  box-sizing: border-box;
  background: #0f0a00;
  color: #e8d0a0;
  border: 1px solid #6a4800;
  border-radius: 4px;
  padding: 5px 7px;
  font-size: 12px;
  font-family: 'Consolas', monospace;
  resize: vertical;
  outline: none;
  &:focus { border-color: #d4a030; }
`

const redirectActionRowCss = css`
  display: flex;
  gap: 5px;
`

const redirectSendButtonCss = css`
  flex: 1;
  background: #14532d;
  color: #4ade80;
  border: 1px solid #166534;
  border-radius: 4px;
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  transition: background 0.15s;
  &:hover { background: #166534; }
  &:disabled { opacity: 0.4; cursor: default; }
`

const redirectCancelButtonCss = css`
  flex: 1;
  background: #1f1f1f;
  color: #eef3ff;
  border: 1px solid #425272;
  border-radius: 4px;
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: 'Consolas', monospace;
  transition: background 0.15s;
  &:hover { background: #34435f; }
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


// Follow-Up button styles (4th column of completed turn)
const followUpColumnCss = css`
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: stretch;
  border-left: 1px solid #22304d;
  padding-left: 14px;
  min-width: 120px;
  max-width: 140px;
`

const followUpButtonCss = css`
  background: #0a120a;
  color: #60a060;
  border: 1px solid #1a401a;
  border-radius: 7px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  text-align: center;
  transition: background 0.15s, border-color 0.15s;
  &:hover { background: #102010; border-color: #2a6a2a; }
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
// JsonArgsViewer
// ---------------------------------------------------------------------------

function formatJsonLeaf(value: unknown): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value) ?? 'undefined'
}

function JsonEntry({ name, value, depth }: { name: string; value: unknown; depth: number }): React.ReactElement {
  const isNested = value !== null && typeof value === 'object'

  if (isNested) {
    const entries: [string, unknown][] = Array.isArray(value)
      ? (value as unknown[]).map((v, i) => [String(i), v])
      : Object.entries(value as Record<string, unknown>)
    return (
      <>
        <div css={jsonRowCss} style={{ paddingLeft: depth * 16 }}>
          <span css={jsonKeyCss}>{name}</span>
        </div>
        {entries.map(([k, v]) => (
          <JsonEntry key={k} name={k} value={v} depth={depth + 1} />
        ))}
      </>
    )
  }

  const text = formatJsonLeaf(value)
  const isMultiline = typeof value === 'string' && value.includes('\n')

  return (
    <div css={jsonRowCss} style={{ paddingLeft: depth * 16 }}>
      <span css={jsonKeyCss}>{name}</span>
      <code css={isMultiline ? jsonValueScrollableCss : jsonValueCss}>{text}</code>
    </div>
  )
}

function JsonArgsViewer({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args)
  if (entries.length === 0) return null
  return (
    <div>
      {entries.map(([k, v]) => (
        <JsonEntry key={k} name={k} value={v} depth={0} />
      ))}
    </div>
  )
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
  const { scrollRef, contentRef } = useStickToBottom()

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
        <div css={toolCallsGroupCss} ref={scrollRef}><div ref={contentRef}>
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
                  <div css={toolArgsCss}><JsonArgsViewer args={tc.args} /></div>
                )}
                {hasResult && (
                  <div css={toolResultCss}><Ansi>{displayResult}</Ansi></div>
                )}
              </div>
            )
          })}
        </div></div>
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

// ---------------------------------------------------------------------------
// ToolApprovalBubble
// ---------------------------------------------------------------------------

function ToolApprovalBubble({
  item,
  onApprove,
  onDeny,
  onDenyWithRedirect,
  onDenyAndStop,
}: {
  item: ApprovalItem
  onApprove: (id: string) => void
  onDeny: (id: string) => void
  onDenyWithRedirect: (id: string, message: string) => void
  onDenyAndStop: (id: string) => void
}) {
  const [showRedirect, setShowRedirect] = useState(false)
  const [redirectText, setRedirectText] = useState('')

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
        <div css={approvalArgsCss}><JsonArgsViewer args={item.args} /></div>
      )}
      <div css={approvalButtonRowCss}>
        <button css={approveButtonCss} onClick={() => onApprove(item.id)}>Approve</button>
        <button css={denyButtonCss} onClick={() => onDeny(item.id)}>Deny</button>
        <button css={denyRedirectButtonCss} onClick={() => setShowRedirect(r => !r)}>Deny &amp; Redirect</button>
        <button css={denyAndStopButtonCss} onClick={() => onDenyAndStop(item.id)}>Deny &amp; Stop</button>
      </div>
      {showRedirect && (
        <div css={redirectInputAreaCss}>
          <textarea
            css={redirectTextareaCss}
            rows={3}
            placeholder="Explain why and suggest an alternative..."
            value={redirectText}
            onChange={e => setRedirectText(e.target.value)}
            autoFocus
          />
          <div css={redirectActionRowCss}>
            <button
              css={redirectSendButtonCss}
              disabled={!redirectText.trim()}
              onClick={() => onDenyWithRedirect(item.id, redirectText.trim())}
            >
              Send
            </button>
            <button
              css={redirectCancelButtonCss}
              onClick={() => { setShowRedirect(false); setRedirectText('') }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// TurnContainer
// ---------------------------------------------------------------------------

function TurnContainer({
  turn,
  isLastTurn,
  onViewFull,
  onApprove,
  onDeny,
  onDenyWithRedirect,
  onDenyAndStop,
  onFollowUp,
}: {
  turn: Turn
  isLastTurn: boolean
  onViewFull: (content: string) => void
  onApprove: (id: string) => void
  onDeny: (id: string) => void
  onDenyWithRedirect: (id: string, message: string) => void
  onDenyAndStop: (id: string) => void
  onFollowUp: (text: string) => void
}) {
  const [showFollowUpWidget, setShowFollowUpWidget] = useState(false)
  const [followUpText, setFollowUpText] = useState('')
  const [compactionModalSubturnId, setCompactionModalSubturnId] = useState<string | null>(null)

  const { todoItems, approvalItems, impossible, subturns, streaming, isInterimStreaming, interimShowCharCount, interimCharCount, interrupted } = turn

  const { scrollRef: toolsScrollRef, contentRef: toolsContentRef } = useStickToBottom()
  const { scrollRef: outcomesScrollRef, contentRef: outcomesContentRef } = useStickToBottom()
  const hasPendingApproval = approvalItems.some(a => !a.resolved)
  const resolvedApprovals = approvalItems.filter(a => a.resolved)
  const pendingApprovals = approvalItems.filter(a => !a.resolved)

  const lastSubturn = subturns[subturns.length - 1]
  const lastSubturnExchanges = lastSubturn?.exchanges ?? []

  // Collect tool call groups from ALL subturns (right column — grows as subturns are added)
  const toolCallGroups = subturns
    .map((st, idx) => ({ subturnIdx: idx, subturnId: st.id, toolCalls: st.exchanges.flatMap(ex => ex.toolCalls) }))
    .filter(g => g.toolCalls.length > 0)
  const hasMultipleToolGroups = toolCallGroups.length > 1
  const totalToolCallCount = toolCallGroups.reduce((n, g) => n + g.toolCalls.length, 0)

  // Display content for the current/last subturn: final exchange or live streaming
  const lastExchange = lastSubturnExchanges[lastSubturnExchanges.length - 1]
  const finalExchange = lastSubturnExchanges.find(ex => ex.isFinal)
  const liveContent = streaming && !isInterimStreaming && lastExchange && !lastExchange.isFinal && lastExchange.toolCalls.length === 0
    ? lastExchange.assistantContent
    : undefined
  const displayContent = finalExchange?.assistantContent ?? liveContent ?? ''

  // Reasoning from the latest exchange in the last subturn
  const reasoning = [...lastSubturnExchanges].reverse().find(ex => ex.reasoning)?.reasoning ?? ''

  // IRAT thinking: concatenation of all last-subturn exchanges
  const iratThinking = lastSubturnExchanges
    .map(ex => ex.iratThinking)
    .filter(Boolean)
    .join('\n\n---\n\n')

  const isStreamingFinal = streaming && !isInterimStreaming
  const showPlaceholder = streaming && !displayContent && !isInterimStreaming && totalToolCallCount === 0

  const hasBanner = !!turn.taskTitle || (turn.loadedSkills?.length ?? 0) > 0

  return (
    <div css={turnWrapperCss}>
      {hasBanner ? (
        <div css={turnBannerCss}>
          <span css={taskTitleCss}>
            {turn.taskTitle ? `Task: ${turn.taskTitle}` : ''}
          </span>
          {turn.loadedSkills && turn.loadedSkills.length > 0 && (
            <div css={skillPillsRowCss}>
              {turn.loadedSkills.map(skillName => (
                <span key={skillName} css={skillPillCss}>{stripMdExtension(skillName)}</span>
              ))}
            </div>
          )}
        </div>
      ) : null}
      <div css={hasBanner ? turnContainerCss : turnContainerNoTitleCss}>
      {/* Left column: user message(s) + AI content — one bubble-group per subturn */}
      <div css={leftColumnCss}>
        <>
          {subturns.map((st, stIdx) => {
            const isLast = stIdx === subturns.length - 1
            const stFinal = st.exchanges.find(ex => ex.isFinal)
            const stContent = isLast ? displayContent : (stFinal?.assistantContent ?? '')
            return (
              <React.Fragment key={st.id}>
                <div css={userBubbleCss}>{st.userText}</div>
                {isLast && interimShowCharCount && (interimCharCount > 0 || isInterimStreaming) && (
                  <div css={interimBubbleCss}>
                    AI interim response: {interimCharCount} chars
                  </div>
                )}
                {stContent ? (
                  <div css={assistantBubbleCss} style={!isLast ? { opacity: 0.7 } : undefined}>
                    <TextPresenter
                      content={stContent}
                      maxHeight={isLast ? 600 : 300}
                      streaming={isLast && isStreamingFinal}
                    />
                  </div>
                ) : isLast && showPlaceholder ? (
                  <div css={streamingPlaceholderCss}>…</div>
                ) : null}
                {(() => {
                  if (!st.detailedSummary) return null
                  if (isLast && streaming) return null
                  const summary = st.detailedSummary
                  const previewText = summary.slice(0, 200) + (summary.length > 200 ? '…' : '')
                  return (
                    <div css={compactionBubbleCss}>
                      <span css={compactionTextCss}>{previewText}</span>
                      <button css={compactionDetailsButtonCss} onClick={() => setCompactionModalSubturnId(st.id)}>Details</button>
                    </div>
                  )
                })()}
              </React.Fragment>
            )
          })}
        </>
        {impossible ? (
          <div css={impossibleBubbleCss}>
            <span css={impossibleLabelCss}>Task impossible</span>
            <span css={impossibleReasonCss}>{impossible}</span>
          </div>
        ) : null}
        {interrupted && (
          <div css={interruptedBubbleCss}>Connection interrupted</div>
        )}
      </div>

      {/* Right column: reasoning + irat thinking + tool calls (scoped to last subturn) */}
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
        {iratThinking ? (
          <div css={iratThinkingWrapperCss}>
            <TextPresenter
              content={iratThinking}
              maxHeight={200}
              streaming={false}
              initialMode="plain"
              showToggle={false}
            />
          </div>
        ) : null}
        {totalToolCallCount > 0 && (
          <div css={toolCallsGroupCss} ref={toolsScrollRef}>
            <div ref={toolsContentRef}>
              {toolCallGroups.map((group) => (
                <React.Fragment key={group.subturnId}>
                  {hasMultipleToolGroups && (
                    <div css={subturnDividerCss}>subturn {group.subturnIdx + 1}</div>
                  )}
                  {group.toolCalls.map(tc => (
                    <ToolCallCard key={tc.id} tc={tc} onViewFull={onViewFull} />
                  ))}
                </React.Fragment>
              ))}
            </div>
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

      {/* Fourth column: follow-up button (last completed turn) */}
      {isLastTurn && turn.completed && !streaming ? (
        <div css={followUpColumnCss}>
          {showFollowUpWidget ? (
            <>
              <textarea
                css={redirectTextareaCss}
                rows={3}
                placeholder="Follow up on this turn..."
                value={followUpText}
                onChange={e => setFollowUpText(e.target.value)}
                autoFocus
                style={{ minHeight: 60 }}
              />
              <div css={redirectActionRowCss}>
                <button
                  css={redirectSendButtonCss}
                  disabled={!followUpText.trim()}
                  onClick={() => {
                    const msg = followUpText.trim()
                    onFollowUp(msg)
                    setShowFollowUpWidget(false)
                    setFollowUpText('')
                  }}
                >
                  Send
                </button>
                <button
                  css={redirectCancelButtonCss}
                  onClick={() => { setShowFollowUpWidget(false); setFollowUpText('') }}
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <button css={followUpButtonCss} onClick={() => setShowFollowUpWidget(true)}>
              Follow Up
            </button>
          )}
        </div>
      ) : (
        <div />
      )}

      {/* Full-width bottom row: approval panel */}
      {approvalItems.length > 0 && (
        <div css={approvalRowCss}>
          <div css={approvalInnerGridCss}>

            {/* Col 1: Resolved approval chips, grouped by subturn */}
            <div css={approvalCol1Css}>
              <div css={approvalColHeaderCss}>Outcomes</div>
              {resolvedApprovals.length === 0 ? (
                <div css={activeDialogPlaceholderCss}>—</div>
              ) : (
                <div css={outcomesScrollCss} ref={outcomesScrollRef}>
                  <div ref={outcomesContentRef} css={approvalListContentCss(3)}>
                  {(() => {
                    // Group consecutive resolved approvals by subturnId for dividers
                    const groups: { subturnId: string | undefined; items: typeof resolvedApprovals }[] = []
                    for (const item of resolvedApprovals) {
                      const last = groups[groups.length - 1]
                      if (last && last.subturnId === item.subturnId) {
                        last.items.push(item)
                      } else {
                        groups.push({ subturnId: item.subturnId, items: [item] })
                      }
                    }
                    const showDividers = groups.length > 1
                    return groups.map((group, gIdx) => (
                      <React.Fragment key={group.subturnId ?? gIdx}>
                        {showDividers && (
                          <div css={subturnDividerCss}>
                            {group.subturnId
                              ? `subturn ${subturns.findIndex(st => st.id === group.subturnId) + 1}`
                              : `group ${gIdx + 1}`}
                          </div>
                        )}
                        {group.items.map(item => (
                          <div key={item.id} css={outcomeApprovalChipCss(item.resolved!.approved)} title={item.tool_name}>
                            {item.resolved!.approved ? '✓' : '✗'} {item.tool_name}
                          </div>
                        ))}
                      </React.Fragment>
                    ))
                  })()}
                  </div>
                </div>
              )}
            </div>

            {/* Col 2: Active approval dialogs */}
            <div css={approvalCol2Css}>
              {hasPendingApproval ? (
                <div css={approvalColHeaderPendingCss}>⚠ Approval Needed</div>
              ) : (
                <div css={approvalColHeaderCss}>Active</div>
              )}
              {pendingApprovals.length === 0 ? (
                <div css={activeDialogPlaceholderCss}>—</div>
              ) : (
                <>
                  {pendingApprovals.map(item => (
                    <ToolApprovalBubble
                      key={item.id} item={item}
                      onApprove={onApprove} onDeny={onDeny}
                      onDenyWithRedirect={onDenyWithRedirect} onDenyAndStop={onDenyAndStop}
                    />
                  ))}
                </>
              )}
            </div>

            {/* Col 3: empty (reserved) */}
            <div css={approvalCol3Css} />

          </div>
        </div>
      )}
      </div>
      {compactionModalSubturnId && (() => {
        const st = subturns.find(s => s.id === compactionModalSubturnId)
        if (!st?.detailedSummary) return null
        return (
          <div css={compactionModalOverlayCss} onClick={() => setCompactionModalSubturnId(null)}>
            <div css={compactionModalCss} onClick={e => e.stopPropagation()}>
              <div css={compactionModalTitleCss}>Context Notes</div>
              <div css={compactionModalBodyCss}>{st.detailedSummary}</div>
              <button css={compactionModalCloseCss} onClick={() => setCompactionModalSubturnId(null)}>Close</button>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Chat() {
  const navigate = useNavigate()
  // Session ID: read from sessionStorage on mount (idempotent — repeated mounts
  // return the same ID; only generates a new UUID the very first time).
  const [sessionId] = useState<string>(() => {
    // URL param takes priority (set by `slbp session new` which opens the browser
    // with ?sessionId=<uuid> pointing to a server-created session).
    const urlId = new URLSearchParams(window.location.search).get('sessionId')
    if (urlId) {
      sessionStorage.setItem('session_id', urlId)
      return urlId
    }
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
  const [sessionCost, setSessionCost] = useState<number | null>(null)

  const { scrollRef: threadRef, contentRef: threadContentRef, scrollToBottom } = useStickToBottom()

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
        const subturnId = data.subturn_id as string | undefined
        setThread(prev => {
          if (prev.some(t => t.id === id)) {
            // Continuation: append new subturn to existing turn
            return prev.map(t => {
              if (t.id !== id) return t
              const newSt: Subturn = { id: subturnId ?? crypto.randomUUID(), userText, exchanges: [] }
              return { ...t, subturns: [...t.subturns, newSt], completed: false, streaming: false }
            })
          } else {
            return [...prev, { ...newTurn(id, userText, subturnId), streaming: false }]
          }
        })
        break
      }
      case 'replay_content_snapshot': {
        const subturnId = data.subturn_id as string
        const exchangeIdx = data.exchange_idx as number
        const assistantContent = (data.assistant_content as string) ?? ''
        const reasoning = (data.reasoning as string) ?? ''
        updateTurn(turnId, t => {
          const subturns = [...t.subturns]
          const stIdx = subturns.findIndex(st => st.id === subturnId)
          if (stIdx < 0) return t
          const st = { ...subturns[stIdx] }
          const exchanges = [...st.exchanges]
          while (exchanges.length <= exchangeIdx) exchanges.push(emptyExchange())
          exchanges[exchangeIdx] = { ...exchanges[exchangeIdx], assistantContent, reasoning }
          st.exchanges = exchanges
          subturns[stIdx] = st
          return { ...t, subturns }
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
          const subturns = [...t.subturns]
          const lastIdx = subturns.length - 1
          if (lastIdx < 0) return t
          const lastSt = { ...subturns[lastIdx] }
          const exchanges = [...lastSt.exchanges]
          const lastExIdx = exchanges.length - 1
          if (lastExIdx >= 0 && !exchanges[lastExIdx].isFinal) {
            if (!exchanges[lastExIdx].toolCalls.some(e => e.id === tc.id)) {
              exchanges[lastExIdx] = { ...exchanges[lastExIdx], toolCalls: [...exchanges[lastExIdx].toolCalls, tc] }
            }
          } else {
            exchanges.push({ ...emptyExchange(), toolCalls: [tc] })
          }
          lastSt.exchanges = exchanges
          subturns[lastIdx] = lastSt
          return { ...t, subturns }
        })
        break
      }
      case 'tool_call_start': {
        const id = data.id as string
        const startedAt = data.started_at as number
        updateTurn(turnId, t => ({
          ...t,
          subturns: t.subturns.map(st => ({
            ...st,
            exchanges: st.exchanges.map(ex => ({
              ...ex,
              toolCalls: ex.toolCalls.map(tc => tc.id === id ? { ...tc, startedAt } : tc),
            })),
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
          subturns: t.subturns.map(st => ({
            ...st,
            exchanges: st.exchanges.map(ex => ({
              ...ex,
              toolCalls: ex.toolCalls.map(tc =>
                tc.id === id ? { ...tc, result, ...(finishedAt !== undefined ? { finishedAt } : {}) } : tc
              ),
            })),
          })),
        }))
        break
      }
      case 'irat_thinking_flush': {
        const subturnId = data.subturn_id as string
        const idx = data.exchange_idx as number
        const text = (data.text as string) ?? ''
        updateTurn(turnId, t => {
          const subturns = [...t.subturns]
          const stIdx = subturns.findIndex(st => st.id === subturnId)
          if (stIdx < 0) return t
          const st = { ...subturns[stIdx] }
          const exchanges = [...st.exchanges]
          while (exchanges.length <= idx) exchanges.push(emptyExchange())
          exchanges[idx] = { ...exchanges[idx], iratThinking: text }
          st.exchanges = exchanges
          subturns[stIdx] = st
          return { ...t, subturns }
        })
        break
      }
      case 'subturn_compaction': {
        const subturnId = data.subturn_id as string
        const compaction = data.compaction as string
        updateTurn(turnId, t => ({
          ...t,
          subturns: t.subturns.map(st =>
            st.id === subturnId ? { ...st, detailedSummary: compaction } : st
          ),
        }))
        break
      }
      case 'begin_interim_stream':
        updateTurn(turnId, t => ({
          ...t,
          isInterimStreaming: true,
          interimShowCharCount: !!(data.show_char_count),
        }))
        break
      case 'begin_final_summary':
        updateTurn(turnId, t => {
          const subturns = [...t.subturns]
          const lastIdx = subturns.length - 1
          if (lastIdx < 0) return t
          const lastSt = { ...subturns[lastIdx] }
          const exchanges = [...lastSt.exchanges]
          if (exchanges.length > 0) {
            exchanges[exchanges.length - 1] = { ...exchanges[exchanges.length - 1], isInterim: true }
          }
          lastSt.exchanges = exchanges
          subturns[lastIdx] = lastSt
          return { ...t, isInterimStreaming: false, subturns }
        })
        break
      case 'todo_list_update':
        updateTurn(turnId, t => ({ ...t, todoItems: data.items as TodoItem[] }))
        break
      case 'approval_request': {
        const item: ApprovalItem = {
          id: data.id as string,
          tool_name: data.tool_name as string,
          args: data.args as Record<string, unknown>,
          subturnId: (data.subturn_id as string | undefined) ?? undefined,
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
      case 'message_done': {
        const content = data.content as string | null
        updateTurn(turnId, t => {
          if (content !== null) {
            const subturns = [...t.subturns]
            const lastIdx = subturns.length - 1
            if (lastIdx >= 0) {
              const lastSt = { ...subturns[lastIdx] }
              const exchanges = [...lastSt.exchanges]
              if (exchanges.length > 0) {
                exchanges[exchanges.length - 1] = { ...exchanges[exchanges.length - 1], assistantContent: content, isFinal: true }
              } else {
                exchanges.push({ ...emptyExchange(), assistantContent: content, isFinal: true })
              }
              lastSt.exchanges = exchanges
              subturns[lastIdx] = lastSt
              return { ...t, completed: true, streaming: false, isInterimStreaming: false, subturns }
            }
          }
          return { ...t, completed: true, streaming: false, isInterimStreaming: false }
        })
        break
      }
      case 'error': {
        const message = data.message as string
        updateTurn(turnId, t => {
          const subturns = [...t.subturns]
          const lastIdx = subturns.length - 1
          if (lastIdx < 0) return { ...t, completed: true, streaming: false }
          const lastSt = { ...subturns[lastIdx] }
          const exchanges = [...lastSt.exchanges]
          if (exchanges.length === 0) {
            exchanges.push({ ...emptyExchange(), assistantContent: `⚠ ${message}`, isFinal: true })
          } else {
            exchanges[exchanges.length - 1] = { ...exchanges[exchanges.length - 1], assistantContent: `⚠ ${message}`, isFinal: true }
          }
          lastSt.exchanges = exchanges
          subturns[lastIdx] = lastSt
          return { ...t, completed: true, streaming: false, subturns }
        })
        break
      }
      case 'task_title':
        updateTurn(turnId, t => ({ ...t, taskTitle: data.title as string }))
        break
      case 'skills_loaded':
        updateTurn(turnId, t => ({ ...t, loadedSkills: data.skill_names as string[] }))
        break
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
    function onSessionCostUpdate({ total_usd }: { total_usd: number }) { setSessionCost(total_usd) }
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
        inProgress.interimShowCharCount = false
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
    function onEventReplay({ events, replay_complete }: { events: { id: string; type: string; data: Record<string, unknown> }[]; replay_complete?: boolean }) {
      if (events && events.length > 0) {
        // Clear interrupted state on any streaming turns before replaying
        setThread(prev => prev.map(t => t.interrupted ? { ...t, interrupted: false, streaming: true } : t))

        for (const ev of events) {
          if (ev.data.event_id) updateLastEventId(ev.data.event_id as string)
          applyReplayEvent(ev.type, ev.data)
        }
        updateLastEventId(events[events.length - 1].id)
      }

      // After replay, force scroll to bottom so the user sees the current state.
      if (replay_complete) {
        scrollToBottom()
      }

      // Replay complete — safe to show UI now
      setIsLoadingBackendState(false)
    }

    // Shell output snapshot: emitted when browser reconnects during a running host_shell.
    function onShellOutputSnapshot({ output }: { output: string }) {
      setThread(prev => prev.map(t => {
        if (!t.streaming) return t
        return {
          ...t,
          subturns: t.subturns.map(st => ({
            ...st,
            exchanges: st.exchanges.map(ex => ({
              ...ex,
              toolCalls: ex.toolCalls.map(tc =>
                tc.name === 'host_shell' && tc.result === undefined
                  ? { ...tc, streamingResult: output }
                  : tc
              ),
            })),
          })),
        }
      }))
    }

    // Live event handlers
    function onTurnStart(data: { event_id?: string; turn_id: string; user_text: string; subturn_id?: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      const { turn_id: id, user_text: userText, subturn_id: subturnId } = data
      setThread(prev => {
        if (prev.some(t => t.id === id)) {
          // Continuation: append new subturn to existing turn
          return prev.map(t => {
            if (t.id !== id) return t
            const newSt: Subturn = { id: subturnId ?? crypto.randomUUID(), userText, exchanges: [] }
            return { ...t, subturns: [...t.subturns, newSt], completed: false, streaming: true, isInterimStreaming: false, interimShowCharCount: false, interimCharCount: 0 }
          })
        } else {
          return [...prev, newTurn(id, userText, subturnId)]
        }
      })
      setBusy(true)
      scrollToBottom()
    }

    function onToken(data: { type: 'reasoning' | 'content'; text: string; turn_id?: string }) {
      const turnId = data.turn_id ?? ''
      if (!turnId) return
      updateTurn(turnId, t => {
        if (!t.streaming) return t
        if (t.isInterimStreaming && data.type === 'content') {
          return { ...t, interimCharCount: t.interimCharCount + data.text.length }
        }
        const subturns = [...t.subturns]
        const lastStIdx = subturns.length - 1
        if (lastStIdx < 0) return t
        const lastSt = { ...subturns[lastStIdx] }
        const exchanges = [...lastSt.exchanges]
        const lastEx = exchanges[exchanges.length - 1]
        const needsNew = !lastEx || lastEx.toolCalls.length > 0 || lastEx.isFinal || lastEx.isInterim
        if (needsNew) {
          exchanges.push({
            assistantContent: data.type === 'content' ? data.text : '',
            reasoning: data.type === 'reasoning' ? data.text : '',
            iratThinking: '',
            toolCalls: [],
            isFinal: false,
          })
        } else {
          const idx = exchanges.length - 1
          exchanges[idx] = {
            ...exchanges[idx],
            assistantContent: data.type === 'content' ? exchanges[idx].assistantContent + data.text : exchanges[idx].assistantContent,
            reasoning: data.type === 'reasoning' ? exchanges[idx].reasoning + data.text : exchanges[idx].reasoning,
          }
        }
        lastSt.exchanges = exchanges
        subturns[lastStIdx] = lastSt
        return { ...t, subturns }
      })
    }

    function onBeginInterimStream(data: { event_id?: string; turn_id?: string; show_char_count?: boolean }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('begin_interim_stream', data)
    }

    function onBeginFinalSummary(data: { event_id?: string; turn_id?: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('begin_final_summary', data)
    }

    function onIratThinkingFlush(data: { event_id?: string; turn_id?: string; subturn_id: string; exchange_idx: number; text: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('irat_thinking_flush', data)
    }

    function onSubturnCompaction(data: { event_id?: string; turn_id?: string; subturn_id: string; compaction: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('subturn_compaction', data)
    }

    function onToolCall(data: { event_id?: string; turn_id?: string; id: string; name: string; args: Record<string, unknown> }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('tool_call', data)
    }

    function onToolCallStart(data: { event_id?: string; turn_id?: string; id: string; started_at: number }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('tool_call_start', data)
    }

    function onToolResultChunk(data: { turn_id?: string; id: string; chunk: string }) {
      const turnId = data.turn_id ?? ''
      updateTurn(turnId, t => ({
        ...t,
        subturns: t.subturns.map(st => ({
          ...st,
          exchanges: st.exchanges.map(ex => ({
            ...ex,
            toolCalls: ex.toolCalls.map(tc =>
              tc.id === data.id ? { ...tc, streamingResult: (tc.streamingResult ?? '') + data.chunk } : tc
            ),
          })),
        })),
      }))
    }

    function onToolResult(data: { event_id?: string; turn_id?: string; id: string; result: string; started_at?: number; finished_at?: number }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('tool_result', data)
    }

    function onMessageDone(data: { event_id?: string; turn_id?: string; content: string | null }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('message_done', data)
      setBusy(false)
      setCancelling(false)
    }

    function onError(data: { event_id?: string; turn_id?: string; message: string }) {
      if (data.event_id) updateLastEventId(data.event_id)
      if (data.turn_id) applyReplayEvent('error', data)
      setBusy(false)
    }

    function onTodoListUpdate(data: { event_id?: string; turn_id?: string; items: TodoItem[] }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('todo_list_update', data)
    }

    function onApprovalRequest(data: { event_id?: string; turn_id?: string; id: string; tool_name: string; args: Record<string, unknown> }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('approval_request', data)
    }

    function onApprovalResolved(data: { event_id?: string; turn_id?: string; id: string; approved: boolean }) {
      if (data.event_id) updateLastEventId(data.event_id)
      applyReplayEvent('approval_resolved', data)
    }

    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    socket.on('pwd_update', onPwdUpdate)
    socket.on('skills_info', onSkillsInfo)
    socket.on('env_info', onEnvInfo)
    socket.on('tools_info', onToolsInfo)
    socket.on('system_prompt', onSystemPrompt)
    socket.on('session_cost_update', onSessionCostUpdate)
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
    socket.on('irat_thinking_flush', onIratThinkingFlush)
    socket.on('subturn_compaction', onSubturnCompaction)
    socket.on('tool_call', onToolCall)
    socket.on('tool_call_start', onToolCallStart)
    socket.on('tool_result_chunk', onToolResultChunk)
    socket.on('tool_result', onToolResult)
    socket.on('message_done', onMessageDone)
    socket.on('error', onError)
    socket.on('todo_list_update', onTodoListUpdate)
    socket.on('approval_request', onApprovalRequest)
    socket.on('approval_resolved', onApprovalResolved)
    socket.on('shell_output_snapshot', onShellOutputSnapshot)
    socket.on('task_title', (data: { turn_id: string; title: string }) => {
      applyReplayEvent('task_title', data)
    })
    socket.on('skills_loaded', (data: { turn_id: string; skill_names: string[] }) => {
      applyReplayEvent('skills_loaded', data)
    })

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
      socket.off('session_cost_update', onSessionCostUpdate)
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
      socket.off('irat_thinking_flush', onIratThinkingFlush)
      socket.off('subturn_compaction', onSubturnCompaction)
      socket.off('tool_call', onToolCall)
      socket.off('tool_call_start', onToolCallStart)
      socket.off('tool_result_chunk', onToolResultChunk)
      socket.off('tool_result', onToolResult)
      socket.off('message_done', onMessageDone)
      socket.off('error', onError)
      socket.off('todo_list_update', onTodoListUpdate)
      socket.off('approval_request', onApprovalRequest)
      socket.off('approval_resolved', onApprovalResolved)
      socket.off('shell_output_snapshot', onShellOutputSnapshot)
      socket.off('task_title')
      socket.off('skills_loaded')
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

  const denyWithRedirect = useCallback((id: string, message: string) => {
    socket.emit('approval_response', { id, approved: false, redirect_message: message })
  }, [])

  const denyAndStop = useCallback((id: string) => {
    socket.emit('approval_response', { id, approved: false })
    socket.emit('cancel_turn')
    setCancelling(true)
  }, [socket])

  const forceContinuation = useCallback((_turnId: string, text: string) => {
    socket.emit('force_continuation', { text })
    setBusy(true)
    scrollToBottom()
  }, [socket, scrollToBottom])

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
    scrollToBottom()
  }, [inputText, busy, connected, scrollToBottom])

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
          sessionId={sessionId}
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
          <div css={headerSideCss}>
            <button css={dashboardButtonCss} onClick={() => navigate('/')} title="Return to dashboard" aria-label="Return to dashboard">
              ⌂
            </button>
          <span css={statusCss}>{connected ? '●' : '○'} {connected ? 'connected' : 'disconnected'}</span>
          </div>
          <span css={sessionIdCss} title={sessionId}>session: {sessionId.slice(0, 8)}</span>
          <div css={headerSideCss}>
            {sessionCost !== null && (
              <span css={sessionCostCss} title="Accumulated session cost (provider-reported)">${formatCost(sessionCost)}</span>
            )}
          </div>
        </div>
        <div css={threadCss} ref={threadRef}>
          <div ref={threadContentRef}>
            {startupToolCalls.length > 0 && (
              <StartupToolCallsCard
                toolCalls={startupToolCalls}
                done={startupDone}
                onViewFull={setModalContent}
              />
            )}
            {thread.map((turn, idx) => (
              <TurnContainer
                key={turn.id}
                turn={turn}
                isLastTurn={idx === thread.length - 1}
                onViewFull={setModalContent}
                onApprove={approve}
                onDeny={deny}
                onDenyWithRedirect={denyWithRedirect}
                onDenyAndStop={denyAndStop}
                onFollowUp={(text) => forceContinuation(turn.id, text)}
              />
            ))}
          </div>
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
          {busy && (
            <button css={stopButtonCss} onClick={cancelTurn} disabled={cancelling}>
              {cancelling ? '...' : 'Stop'}
            </button>
          )}
          <button css={sendButtonCss} onClick={send} disabled={busy || !connected || !inputText.trim()}>
            <span css={busy ? css`visibility: hidden` : undefined}>Send</span>
            {busy && <span css={spinnerCss} />}
          </button>
        </div>
      </div>
    </div>
  )
}
