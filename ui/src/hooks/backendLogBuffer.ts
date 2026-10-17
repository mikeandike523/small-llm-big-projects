import type {
  BackendLogContent,
  BackendLogEntry,
  BackendLogWireEntry,
} from "../types/DebugPanel";

// The central, unfiltered Backend Logs buffer keeps the newest MAX_LOGS
// entries. Filtered views (BackendLogsTab) are subsets of this buffer, so they
// show "matches within the last MAX_LOGS logs".
export const MAX_LOGS = 1000;

export function appendCapped(
  previous: BackendLogEntry[],
  entry: BackendLogEntry,
): BackendLogEntry[] {
  const next = [...previous, entry];
  return next.length > MAX_LOGS ? next.slice(next.length - MAX_LOGS) : next;
}

// Drops empty multi entries and turns one-item multi entries into single
// entries. Returns null for entries that should not be shown.
export function normalizeWireEntry(
  entry: BackendLogWireEntry,
): BackendLogWireEntry | null {
  if (entry.multiple !== true) return entry;
  if (!Array.isArray(entry.content) || entry.content.length === 0) return null;
  if (entry.content.length === 1) {
    return {
      id: entry.id,
      content: entry.content[0] as BackendLogContent,
    };
  }
  return entry;
}

export function withSeq(
  entry: BackendLogWireEntry,
  seq: number,
): BackendLogEntry {
  return { ...entry, seq } as BackendLogEntry;
}
