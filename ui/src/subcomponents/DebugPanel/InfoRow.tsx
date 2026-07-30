import { css } from "@emotion/react";
import { rowCss } from "../../css/DebugPanel";
import { fontMono, spTextMain, spTextTitle } from "../../css/SidePanelTheme";

export const rowLabelCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: ${spTextTitle};
`;

export const rowValueCss = css`
  font-family: ${fontMono};
  font-size: 11px;
  color: ${spTextMain};
  word-break: break-all;
`;

export default function InfoRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div css={rowCss}>
      <span css={rowLabelCss}>{label}</span>
      <span css={rowValueCss}>{value}</span>
    </div>
  );
}
