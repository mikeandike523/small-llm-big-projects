import type {
  BackendLogContent,
  BackendLogEntry,
} from "../../types/DebugPanel";

// Matching rules for the Backend Logs filter bar (BackendLogFilterBar.tsx):
// case-insensitive substring search.
//   - text filter: any content item of the entry (single content, or any row
//     of a multi card, row 1 included).
//   - row-1 filter: only content[0] of multi entries. Single entries -- which
//     includes one-item multis, normalized to single on arrival -- never match.
// Both filters combine with AND; a blank filter is inactive.

// ANSI color codes are rendered by ansi-to-react, not shown as text. Strip them
// so a query matches across color boundaries and never matches the codes.
const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;

// Full JSON.stringify (not the truncated preview), so text hidden behind the
// "view" button still matches.
function contentText(content: BackendLogContent): string {
  const raw =
    content !== null && typeof content === "object"
      ? JSON.stringify(content)
      : String(content);
  return raw.replace(ANSI_RE, "").toLowerCase();
}

// Lazy per-entry search text. Each part is filled only when its own filter is
// applied, once per entry lifetime; evicted entries are garbage-collected out
// of the WeakMap.
interface Haystacks {
  all?: string;
  label?: string | null; // null = not a multi entry (has no row 1)
}
const haystackCache = new WeakMap<BackendLogEntry, Haystacks>();

function haystacksFor(entry: BackendLogEntry): Haystacks {
  let haystacks = haystackCache.get(entry);
  if (haystacks === undefined) {
    haystacks = {};
    haystackCache.set(entry, haystacks);
  }
  return haystacks;
}

function labelHaystack(entry: BackendLogEntry): string | null {
  const haystacks = haystacksFor(entry);
  if (haystacks.label === undefined) {
    haystacks.label =
      entry.multiple === true ? contentText(entry.content[0]) : null;
  }
  return haystacks.label;
}

function allHaystack(entry: BackendLogEntry): string {
  const haystacks = haystacksFor(entry);
  if (haystacks.all === undefined) {
    const parts = entry.multiple === true ? entry.content : [entry.content];
    haystacks.all = parts.map(contentText).join("\n");
  }
  return haystacks.all;
}

export interface AppliedLogFilter {
  text: string;
  label: string;
  // Incremented on every Apply; BackendLogsTab uses it as the list's `key`.
  generation: number;
}

export type LogPredicate = (entry: BackendLogEntry) => boolean;

function normalizeQuery(query: string): string | null {
  return query.trim() === "" ? null : query.toLowerCase();
}

// Returns null when no filter is active (show everything, compute nothing).
export function buildLogPredicate(
  filter: AppliedLogFilter,
): LogPredicate | null {
  const text = normalizeQuery(filter.text);
  const label = normalizeQuery(filter.label);
  if (text === null && label === null) return null;

  return (entry) => {
    // Row-1 check first: cheap, and it short-circuits so the full-text
    // haystack is never built for single entries or non-matching labels.
    if (label !== null) {
      const haystack = labelHaystack(entry);
      if (haystack === null || !haystack.includes(label)) return false;
    }
    return text === null || allHaystack(entry).includes(text);
  };
}
