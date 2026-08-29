import { useState } from "react";
import { useStickToBottom } from "use-stick-to-bottom";
import { BackendLogEntry } from "../../types/DebugPanel";
import { placeholderCss } from "../../css/DebugPanel";
import { css } from "@emotion/react";
import scrollbarCss from "../../css/scrollBarCss";
import BackendLogEntryItem from "./BackendLogEntryItem";
import BackendLogObjectModal from "./BackendLogObjectModal";

export const logsPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  padding: 6px;
  display: flex;
  flex-direction: column;
  ${scrollbarCss}
`;

export default function BackendLogsTab({
  logs,
  visible,
}: {
  logs: BackendLogEntry[];
  visible: boolean;
}) {
  const { scrollRef, contentRef } = useStickToBottom();
  const [viewingEntry, setViewingEntry] = useState<{
    id: number;
    content: Record<string, unknown> | unknown[];
  } | null>(null);

  return (
    <div ref={scrollRef} css={logsPanelCss(visible)}>
      <div ref={contentRef}>
        {logs.length === 0 ? (
          <div css={placeholderCss}>No logs yet.</div>
        ) : (
          logs.map((entry) => (
            <BackendLogEntryItem
              key={entry.id}
              entry={entry}
              onView={setViewingEntry}
            />
          ))
        )}
      </div>
      <BackendLogObjectModal
        entry={viewingEntry}
        onClose={() => setViewingEntry(null)}
      />
    </div>
  );
}
