import type { DesktopDownload } from './downloads';

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = -1;
  do {
    size /= 1024;
    unit += 1;
  } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

export function progressDetail(download: DesktopDownload): string {
  if (download.state === 'finalized') {
    if (download.finalizeReason === 'done') return `${formatBytes(download.receivedBytes)} · Complete`;
    if (download.finalizeReason === 'canceled') return 'Canceled';
    return download.error ?? 'Download failed';
  }
  if (download.error) return download.error;
  const received = formatBytes(download.receivedBytes);
  const total = download.totalBytes > 0 ? ` of ${formatBytes(download.totalBytes)}` : '';
  const speed = download.bytesPerSecond > 0 ? ` · ${formatBytes(download.bytesPerSecond)}/s` : '';
  return `${received}${total}${speed}`;
}

/** Percent complete for a pending download, or null when its size is unknown. */
export function downloadPercent(download: DesktopDownload): number | null {
  if (download.totalBytes <= 0) return null;
  return Math.min(100, (download.receivedBytes / download.totalBytes) * 100);
}

/** CSS-friendly status key: pending | done | failed | canceled. */
export function statusKey(download: DesktopDownload): 'pending' | 'done' | 'failed' | 'canceled' {
  return download.state === 'pending' ? 'pending' : download.finalizeReason;
}
