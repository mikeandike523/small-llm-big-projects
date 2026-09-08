import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { BackendLogEntry } from "../../types/DebugPanel";
import { placeholderCss } from "../../css/DebugPanel";
import { css } from "@emotion/react";
import scrollbarCss from "../../css/scrollBarCss";
import BackendLogEntryItem from "./BackendLogEntryItem";
import BackendLogMultiCard from "./BackendLogMultiCard";
import BackendLogObjectModal from "./BackendLogObjectModal";

export const logsPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  padding: 6px;
  ${scrollbarCss}
`;

// Absolutely-positioned rows inside a sized spacer div (virtualizer layout)
const virtualInnerCss = css`
  position: relative;
  width: 100%;
`;

const virtualRowCss = css`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  padding-bottom: 4px;
`;

export default function BackendLogsTab({
  logs,
  visible,
}: {
  logs: BackendLogEntry[];
  visible: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewingEntry, setViewingEntry] = useState<{
    id: number;
    content: Record<string, unknown> | unknown[];
  } | null>(null);

  const virtualizer = useVirtualizer({
    count: logs.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 48,
    getItemKey: (index) => logs[index].id,
    overscan: 8,
    // Stick-to-bottom: keep the newest log entry in view as entries append,
    // matching the behavior of the tool-calls virtual list in TurnContainer.
    anchorTo: "end",
    followOnAppend: true,
  });

  return (
    <div ref={scrollRef} css={logsPanelCss(visible)}>
      {logs.length === 0 ? (
        <div css={placeholderCss}>No logs yet.</div>
      ) : (
        <div css={virtualInnerCss} style={{ height: virtualizer.getTotalSize() }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const entry = logs[virtualRow.index];
            return (
              <div
                key={entry.id}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                css={virtualRowCss}
                style={{ transform: `translateY(${virtualRow.start}px)` }}
              >
                {entry.multiple === true ? (
                  <BackendLogMultiCard
                    entry={entry}
                    onView={setViewingEntry}
                  />
                ) : (
                  <BackendLogEntryItem
                    entry={entry}
                    onView={setViewingEntry}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
      <BackendLogObjectModal
        entry={viewingEntry}
        onClose={() => setViewingEntry(null)}
      />
    </div>
  );
}
