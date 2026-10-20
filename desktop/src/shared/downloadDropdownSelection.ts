import type { DesktopDownload } from './downloads';

/** Finalized items fill the dropdown up to this many slots when it opens. */
export const DROPDOWN_FINALIZED_FILL = 3;

/**
 * The dropdown's members at the moment it opens: every pending download
 * (newest first), then the newest undismissed finalized downloads, filling up
 * to DROPDOWN_FINALIZED_FILL slots. This is the only place history is pulled
 * into the dropdown -- while it stays open, members are only added (new
 * downloads) or dismissed, never evicted or backfilled.
 */
export function selectDropdownIds(downloads: readonly DesktopDownload[]): string[] {
  const pending = downloads
    .filter((download) => download.state === 'pending')
    .sort((a, b) => b.startedAt - a.startedAt);
  const finalized = downloads
    .flatMap((download) =>
      download.state === 'finalized' && !download.dismissedFromDropdown ? [download] : [],
    )
    .sort((a, b) => b.finalizedAt - a.finalizedAt)
    .slice(0, Math.max(0, DROPDOWN_FINALIZED_FILL - pending.length));
  return [...pending, ...finalized].map((download) => download.id);
}

/** A download that starts while the dropdown is open goes on top. */
export function addToOpenDropdown(ids: readonly string[], newId: string): string[] {
  return ids.includes(newId) ? [...ids] : [newId, ...ids];
}

export interface PendingProgress {
  count: number;
  // Mean percent over pending downloads with a known size; null when none
  // has a known size (the indicator then spins instead).
  meanPercent: number | null;
}

export function pendingProgress(downloads: readonly DesktopDownload[]): PendingProgress {
  const pending = downloads.filter((download) => download.state === 'pending');
  const sized = pending.filter((download) => download.totalBytes > 0);
  const meanPercent =
    sized.length === 0
      ? null
      : sized.reduce(
          (sum, download) => sum + Math.min(100, (download.receivedBytes / download.totalBytes) * 100),
          0,
        ) / sized.length;
  return { count: pending.length, meanPercent };
}
