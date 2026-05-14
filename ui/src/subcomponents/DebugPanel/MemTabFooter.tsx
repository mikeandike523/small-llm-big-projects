import { css } from "@emotion/react";

import { MemKeyEvent } from "../../types/DebugPanel";

export const memEventLabelCss = (type: string) => css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  color: ${type === "deleted" ? "#8a3535" : "#8a6a20"};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
`;

export const memEventEmptyCss = css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  color: #252525;
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
