export type DownloadState = 'pending' | 'finalized';
export type FinalizeReason = 'done' | 'failed' | 'canceled';

interface DesktopDownloadBase {
  id: string;
  filename: string;
  savePath: string;
  receivedBytes: number;
  totalBytes: number;
  bytesPerSecond: number;
  startedAt: number;
  error?: string;
}

export type DesktopDownload = DesktopDownloadBase &
  ({ state: 'pending' } | { state: 'finalized'; finalizeReason: FinalizeReason; finalizedAt: number });

export type FinalizedDownload = Extract<DesktopDownload, { state: 'finalized' }>;

/** What the dropdown view renders: its members, in display order. */
export interface DropdownState {
  items: DesktopDownload[];
}

/** The Downloads icon's rect in the base window, in CSS pixels. */
export interface DropdownAnchor {
  left: number;
  right: number;
  bottom: number;
}

export interface DownloadSettingsSnapshot {
  directory: string;
  defaultDirectory: string;
  usesDefault: boolean;
}
