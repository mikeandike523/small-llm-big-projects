import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { BackendLogEntry } from "../../types/DebugPanel";
import { placeholderCss } from "../../css/DebugPanel";
import { css } from "@emotion/react";
import scrollbarCss from "../../css/scrollBarCss";
import BackendLogEntryItem from "./BackendLogEntryItem";
import BackendLogMultiCard from "./BackendLogMultiCard";
import BackendLogObjectModal from "./BackendLogObjectModal";
import { estimateBackendLogRowHeight } from "../../estimators/backend-log-entry";
import { useStickToEnd } from "../../hooks/useStickToEnd";

// Fallback panel width for the very first render, before scrollRef has
// mounted and clientWidth is available. Every render after mount reads the
// actual width, so this only matters for the first paint's estimate.
const FALLBACK_LOGS_PANEL_WIDTH_PX = 340;

// Outer wrapper: handles absolute positioning and tab visibility within the
// debug panel. Does NOT participate in the grid/flex sizing of its children
// — that is delegated to the inner wrapper below so the autoscroll shine
// anchors against a stable position:relative box (matching TurnContainer's
// toolCallsViewportCss pattern).
export const logsPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
`;

// Inner wrapper: establishes a stable containing block (position:relative)
// for the absolutely-positioned shine, and uses a single grid row to size
// the scroll viewport to fill the available space.
const logsInnerCss = css`
  position: relative;
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-rows: 1fr;
`;

// The actual scroll viewport — padding/overflow unchanged from before the
// split, since estimators/backend-log-entry/constants.ts's
// PANEL_HORIZONTAL_PADDING_PX mirrors this element's padding via clientWidth.
const logsScrollCss = css`
  overflow-y: auto;
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

// Brief glow at the bottom edge, lit while actively auto-scrolling to follow
// new log entries and faded out via CSS transition once that settles.
const autoScrollShineCss = (active: boolean) => css`
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 16px;
  pointer-events: none;
  opacity: ${active ? 1 : 0};
  transition: opacity 220ms ease;
  background: linear-gradient(
    to top,
    rgba(160, 110, 230, 0.55),
    rgba(160, 110, 230, 0)
  );
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

  const estimateLogRowSize = (index: number): number =>
    estimateBackendLogRowHeight(
      logs[index],
      scrollRef.current?.clientWidth ?? FALLBACK_LOGS_PANEL_WIDTH_PX,
    );

  const virtualizer = useVirtualizer({
    count: logs.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: estimateLogRowSize,
    getItemKey: (index) => logs[index].id,
    overscan: 8,
  });
  const isAutoScrolling = useStickToEnd(virtualizer);

  return (
    <div css={logsPanelCss(visible)}>
      <div css={logsInnerCss}>
        <div ref={scrollRef} css={logsScrollCss}>
        {logs.length === 0 ? (
          <div css={placeholderCss}>No logs yet.</div>
        ) : (
          <div
            css={virtualInnerCss}
            style={{ height: virtualizer.getTotalSize() }}
          >
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
        </div>
        <div css={autoScrollShineCss(isAutoScrolling)} />
      </div>
      <BackendLogObjectModal
        entry={viewingEntry}
        onClose={() => setViewingEntry(null)}
      />
    </div>
  );
}
