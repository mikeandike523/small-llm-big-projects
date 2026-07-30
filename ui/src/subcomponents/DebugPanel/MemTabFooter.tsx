import { css } from "@emotion/react";

import { MemKeyEvent } from "../../types/DebugPanel";
import { fontMono, spTextDim } from "../../css/SidePanelTheme";

export const memEventLabelCss = (type: string) => css`
  font-family: ${fontMono};
  font-size: 9px;
  color: ${type === "deleted" ? "#c07268" : "#c9a05a"};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
`;

export const memEventEmptyCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  color: ${spTextDim};
  font-style: italic;
`;

export default function MemTabFooter({ event }: { event: MemKeyEvent | null }) {
  if (!event) {
    return <span css={memEventEmptyCss}>no events</span>;
  }
  const label = event.type === "deleted" ? "deleted" : "set";
  return (
    <span css={memEventLabelCss(event.type)} title={`${label}: "${event.key}"`}>
      {label}: &quot;{event.key}&quot;
    </span>
  );
}
