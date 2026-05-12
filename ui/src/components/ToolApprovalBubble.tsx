import { useState } from "react"
import { ApprovalItem } from "../types"
import { css } from "@emotion/react"
import JsonArgsViewer from "./JsonArgsViewer"

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


export default function ToolApprovalBubble({
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