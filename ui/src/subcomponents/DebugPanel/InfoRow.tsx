import { rowCss, rowLabelCss, rowValueCss } from "../../css/DebugPanel";

export default function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div css={rowCss}>
      <span css={rowLabelCss}>{label}</span>
      <span css={rowValueCss}>{value}</span>
    </div>
  )
}
