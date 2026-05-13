import { useStickToBottom } from "use-stick-to-bottom";
import { BackendLogEntry } from "../../types/DebugPanel";
import { placeholderCss } from "../../css/DebugPanel";
import Ansi from "ansi-to-react";
import { css } from "@emotion/react";
import scrollbarCss from "../../css/scrollBarCss";

export const logLineCss = css`
  font-family: 'Consolas', monospace;
  font-size: 10px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 2px;
`

export const logsPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? 'auto' : 'none'};
  transition: opacity 0.18s ease;
  padding: 6px;
  display: flex;
  flex-direction: column;
  ${scrollbarCss}
`


export default function BackendLogsTab({
  logs,
  visible,
}: {
  logs: BackendLogEntry[];
  visible: boolean;
}) {
  const { scrollRef, contentRef } = useStickToBottom();

  return (
    <div ref={scrollRef} css={logsPanelCss(visible)}>
      <div ref={contentRef}>
        {logs.length === 0 ? (
          <div css={placeholderCss}>No logs yet.</div>
        ) : (
          logs.map((entry) => (
            <div key={entry.id} css={logLineCss}>
              <Ansi>{entry.text}</Ansi>
            </div>
          ))
        )}
      </div>
    </div>
  );
}