import { css } from "@emotion/react"
import { rowCss } from "../../css/DebugPanel";



export const rowLabelCss = css`
  font-family: 'Consolas', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #444;
`

export const rowValueCss = css`
  font-family: 'Consolas', monospace;
  font-size: 11px;
  color: #888;
  word-break: break-all;
`

export default function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div css={rowCss}>
      <span css={rowLabelCss}>{label}</span>
      <span css={rowValueCss}>{value}</span>
    </div>
  )
}
