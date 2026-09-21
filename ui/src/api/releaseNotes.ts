import { useEffect, useState } from "react";

/** Which side's changelog: the web UI (static assets under
 * /ui-release-notes/) or the backend (JSON API under /api/changelog/). */
export type ReleaseSide = "ui" | "backend";

/** Compare two semver strings (e.g. "1.2.3"). Returns negative if a < b, 0 if equal, positive if a > b. */
export function cmpSemver(a: string, b: string): number {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

export type ReleaseIndexEntry = { version: string; date: string; file?: string };
export type ReleaseNote = { version: string; date: string; message: string };

/** Fetch the changelog index for one side. Empty list when unavailable
 * (e.g. no releases yet — a 404 is not an error). */
export function fetchReleaseIndex(side: ReleaseSide): Promise<ReleaseIndexEntry[]> {
  const url =
    side === "ui"
      ? "/ui-release-notes/changelog-index.json"
      : "/api/changelog";
  return fetch(url)
    .then((r) => (r.ok ? r.json() : { releases: [] }))
    .then((d) => d.releases ?? [])
    .catch(() => []);
}

/** Fetch the message text for one version on one side. Null when absent. */
export function fetchReleaseNote(
  side: ReleaseSide,
  version: string,
): Promise<string | null> {
  const url =
    side === "ui"
      ? `/ui-release-notes/${version}.txt`
      : `/api/changelog/${encodeURIComponent(version)}`;
  return fetch(url)
    .then((r) => (r.ok ? (side === "ui" ? r.text() : r.json().then((d) => d.message)) : null))
    .catch(() => null);
}

/** Latest note for one side (message trimmed), or null when no releases yet. */
export function useLatestReleaseNote(side: ReleaseSide): ReleaseNote | null {
  const [note, setNote] = useState<ReleaseNote | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchReleaseIndex(side).then(async (entries) => {
      if (cancelled || entries.length === 0) return;
      // Sort by semver descending so index[0] is always the latest,
      // regardless of the order the server returns.
      const sorted = [...entries].sort((a, b) =>
        cmpSemver(b.version, a.version),
      );
      const top = sorted[0];
      const raw = await fetchReleaseNote(side, top.version);
      if (!cancelled && raw != null) {
        setNote({ version: top.version, date: top.date, message: raw.trim() });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [side]);
  return note;
}

/** Back-compat alias used by VersionWidget (UI side only). */
export const useLatestUiReleaseNote = () => useLatestReleaseNote("ui");
