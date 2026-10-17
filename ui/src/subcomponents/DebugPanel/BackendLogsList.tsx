import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { css } from "@emotion/react";
import { BackendLogEntry } from "../../types/DebugPanel";
import { placeholderCss } from "../../css/DebugPanel";
import scrollbarCss from "../../css/scrollBarCss";
import {
  autoScrollShineCss,
  SHINE_HEIGHT_BACKEND_LOGS_PX,
} from "../../css/autoScrollShineCss";
import BackendLogEntryItem from "./BackendLogEntryItem";
import BackendLogMultiCard from "./BackendLogMultiCard";
import { estimateBackendLogRowHeight } from "../../estimators/backend-log-entry";
import { useStickToEnd } from "../../hooks/useStickToEnd";

// Fallback panel width for the very first render, before scrollRef has
// mounted and clientWidth is available. Every render after mount reads the
// actual width, so this only matters for the first paint's estimate.
const FALLBACK_LOGS_PANEL_WIDTH_PX = 340;

export type ViewingLogEntry = {
  id: number;
  content: Record<string, unknown> | unknown[];
};

// Establishes a stable containing block (position:relative) for the
// absolutely-positioned shine, and uses a single grid row to size the scroll
// viewport to fill the available space (matching TurnContainer's
// toolCallsViewportCss pattern).
const listWrapCss = css`
  position: relative;
  min-height: 0;
  display: grid;
  grid-template-rows: 1fr;
`;

// The actual scroll viewport. estimators/backend-log-entry/constants.ts's
// PANEL_HORIZONTAL_PADDING_PX mirrors this element's padding via clientWidth.
const logsScrollCss = css`
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px;
  min-height: 0;
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

// The virtualized, stick-to-end log viewport. BackendLogsTab remounts this
// (via `key`) on every filter Apply, which resets the virtualizer and
// useStickToEnd so the fresh list starts attached to the bottom.
export default function BackendLogsList({
  logs,
  emptyText,
  onView,
}: {
  logs: BackendLogEntry[];
  emptyText: string;
  onView: (entry: ViewingLogEntry) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

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
    // Only for eviction anchoring: when the oldest row is dropped from the
    // capped buffer, TanStack keeps the on-screen row fixed instead of letting
    // content slide up under a scrolled-up reader. Following the end is owned
    // by useStickToEnd -- do NOT add followOnAppend. See
    // future_feature_plans/log_stick_to_bottom_pointerdown.md if eviction
    // ever causes accidental unsticking.
    anchorTo: "end",
  });
  const isAutoScrolling = useStickToEnd(virtualizer);

  return (
    <div css={listWrapCss}>
      <div ref={scrollRef} css={logsScrollCss}>
        {logs.length === 0 ? (
          <div css={placeholderCss}>{emptyText}</div>
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
                    <BackendLogMultiCard entry={entry} onView={onView} />
                  ) : (
                    <BackendLogEntryItem entry={entry} onView={onView} />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div
        css={autoScrollShineCss(isAutoScrolling, SHINE_HEIGHT_BACKEND_LOGS_PX)}
      />
    </div>
  );
}
