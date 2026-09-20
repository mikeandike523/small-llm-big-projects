import { useEffect, useState } from "react";

export type UiReleaseIndexEntry = { version: string; date: string; file: string };
export type UiReleaseNote = { version: string; date: string; message: string };

export function fetchUiReleaseIndex(): Promise<UiReleaseIndexEntry[]> {
  return fetch("/ui-release-notes/changelog-index.json")
    .then((r) => (r.ok ? r.json() : { releases: [] }))
    .then((d) => d.releases ?? [])
    .catch(() => []);
}

export function fetchUiReleaseNote(version: string): Promise<string | null> {
  return fetch(`/ui-release-notes/${version}.txt`)
    .then((r) => (r.ok ? r.text() : null))
    .catch(() => null);
}

/** Latest note message, or null when no releases exist yet. */
export function useLatestUiReleaseNote(): UiReleaseNote | null {
  const [note, setNote] = useState<UiReleaseNote | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchUiReleaseIndex().then(async (entries) => {
      if (cancelled || entries.length === 0) return;
      const top = entries[0];
      const message = await fetchUiReleaseNote(top.version);
      if (!cancelled && message != null) {
        setNote({ version: top.version, date: top.date, message: message.trim() });
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return note;
}
