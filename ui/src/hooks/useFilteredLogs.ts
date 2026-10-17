import { useRef } from "react";
import type { BackendLogEntry } from "../types/DebugPanel";
import type { LogPredicate } from "../subcomponents/DebugPanel/backendLogFilter";

interface FilterState {
  predicate: LogPredicate;
  result: BackendLogEntry[];
  lastTestedSeq: number;
}

function lastSeqOf(logs: BackendLogEntry[]): number {
  return logs[logs.length - 1]?.seq ?? -1;
}

// Incrementally filtered view of the central backend-log buffer.
//
// A new predicate (one per Apply) runs one full pass. After that, each buffer
// update only:
//   - trims evicted entries from the front (the buffer evicts from the front
//     and the view keeps buffer order, so a seq comparison suffices), and
//   - tests entries newer than the last tested seq.
// When neither changes anything, the same array is returned so the list does
// not re-render for non-matching logs.
//
// The ref is a render-time cache. A repeated render (strict mode) finds no new
// seqs and returns the same result.
export function useFilteredLogs(
  logs: BackendLogEntry[],
  predicate: LogPredicate | null,
): BackendLogEntry[] {
  const stateRef = useRef<FilterState | null>(null);

  if (predicate === null) {
    stateRef.current = null;
    return logs;
  }

  const state = stateRef.current;
  if (state === null || state.predicate !== predicate) {
    const startedAt = performance.now();
    const result = logs.filter(predicate);
    if (import.meta.env.DEV) {
      const elapsedMs = (performance.now() - startedAt).toFixed(1);
      console.debug(`[logs] filtered ${logs.length} in ${elapsedMs}ms`);
    }
    stateRef.current = { predicate, result, lastTestedSeq: lastSeqOf(logs) };
    return result;
  }

  const oldestSeq = logs[0]?.seq ?? Infinity;
  let evicted = 0;
  while (
    evicted < state.result.length &&
    state.result[evicted].seq < oldestSeq
  ) {
    evicted++;
  }

  let firstNew = logs.length;
  while (firstNew > 0 && logs[firstNew - 1].seq > state.lastTestedSeq) {
    firstNew--;
  }
  const added = logs.slice(firstNew).filter(predicate);

  if (evicted > 0 || added.length > 0) {
    state.result = [...state.result.slice(evicted), ...added];
  }
  state.lastTestedSeq = Math.max(state.lastTestedSeq, lastSeqOf(logs));
  return state.result;
}
