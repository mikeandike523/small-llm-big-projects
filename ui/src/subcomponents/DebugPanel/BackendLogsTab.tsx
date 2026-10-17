import { useMemo, useState } from "react";
import { BackendLogEntry } from "../../types/DebugPanel";
import { css } from "@emotion/react";
import BackendLogObjectModal from "./BackendLogObjectModal";
import BackendLogsList, { ViewingLogEntry } from "./BackendLogsList";
import BackendLogFilterBar from "./BackendLogFilterBar";
import { AppliedLogFilter, buildLogPredicate } from "./backendLogFilter";
import { useFilteredLogs } from "../../hooks/useFilteredLogs";

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
  grid-template-rows: auto 1fr;
`;

// `logs` is the central, unfiltered buffer (useSocketWiring). Filters apply
// only on Apply: typing changes nothing until then. Every Apply (including
// Clear, and Apply with unchanged filters) remounts BackendLogsList, which
// resets the virtualizer and useStickToEnd so the view snaps to the newest
// log and is attached to the bottom.
export default function BackendLogsTab({
  logs,
  visible,
}: {
  logs: BackendLogEntry[];
  visible: boolean;
}) {
  const [draftText, setDraftText] = useState("");
  const [draftLabel, setDraftLabel] = useState("");
  const [applied, setApplied] = useState<AppliedLogFilter>({
    text: "",
    label: "",
    generation: 0,
  });
  const [viewingEntry, setViewingEntry] = useState<ViewingLogEntry | null>(
    null,
  );

  // A new predicate per Apply (generation is part of `applied`), so
  // useFilteredLogs runs a fresh full pass on every Apply.
  const predicate = useMemo(() => buildLogPredicate(applied), [applied]);
  const visibleLogs = useFilteredLogs(logs, predicate);

  const apply = (text: string, label: string) =>
    setApplied((previous) => ({
      text,
      label,
      generation: previous.generation + 1,
    }));
  const clear = () => {
    setDraftText("");
    setDraftLabel("");
    apply("", "");
  };

  return (
    <div css={logsPanelCss(visible)}>
      <div css={logsLayoutCss}>
        <BackendLogFilterBar
          text={draftText}
          label={draftLabel}
          onTextChange={setDraftText}
          onLabelChange={setDraftLabel}
          onApply={() => apply(draftText, draftLabel)}
          onClear={clear}
          pending={draftText !== applied.text || draftLabel !== applied.label}
          filtered={predicate !== null}
          matchCount={visibleLogs.length}
          totalCount={logs.length}
        />
        <BackendLogsList
          key={applied.generation}
          logs={visibleLogs}
          emptyText={predicate !== null ? "No matching logs." : "No logs yet."}
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
