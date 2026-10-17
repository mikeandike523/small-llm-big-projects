import { useState } from "react";
import { BackendLogEntry } from "../../types/DebugPanel";
import { css } from "@emotion/react";
import BackendLogObjectModal from "./BackendLogObjectModal";
import BackendLogsList, { ViewingLogEntry } from "./BackendLogsList";

// Outer wrapper: handles absolute positioning and tab visibility within the
// debug panel. Does NOT participate in the grid/flex sizing of its children
// — that is delegated to the inner layout below.
export const logsPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
`;

const logsLayoutCss = css`
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-rows: 1fr;
`;

export default function BackendLogsTab({
  logs,
  visible,
}: {
  logs: BackendLogEntry[];
  visible: boolean;
}) {
  const [viewingEntry, setViewingEntry] = useState<ViewingLogEntry | null>(
    null,
  );

  return (
    <div css={logsPanelCss(visible)}>
      <div css={logsLayoutCss}>
        <BackendLogsList
          logs={logs}
          emptyText="No logs yet."
          onView={setViewingEntry}
        />
      </div>
      <BackendLogObjectModal
        entry={viewingEntry}
        onClose={() => setViewingEntry(null)}
      />
    </div>
  );
}
