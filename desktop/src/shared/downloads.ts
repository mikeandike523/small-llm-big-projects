export type DesktopDownloadState = 'progressing' | 'completed' | 'cancelled' | 'failed';

export interface DesktopDownload {
  id: string;
  filename: string;
  savePath: string;
  receivedBytes: number;
  totalBytes: number;
  bytesPerSecond: number;
  state: DesktopDownloadState;
  startedAt: number;
  error?: string;
}

export interface DownloadSettingsSnapshot {
  directory: string;
  defaultDirectory: string;
  usesDefault: boolean;
}
