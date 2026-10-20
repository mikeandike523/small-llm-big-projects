import type { DesktopDownload } from './downloads';

/**
 * The dropdown only opens because a download started. Its members at that
 * moment: the new download on top, then every other pending download (newest
 * first). History stays on the Downloads page -- while the dropdown is open,
 * members are only added (new downloads) or dismissed, never backfilled.
 */
export function selectDropdownIds(downloads: readonly DesktopDownload[], newId: string): string[] {
  const otherPending = downloads
    .filter((download) => download.state === 'pending' && download.id !== newId)
    .sort((a, b) => b.startedAt - a.startedAt)
    .map((download) => download.id);
  return [newId, ...otherPending];
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
