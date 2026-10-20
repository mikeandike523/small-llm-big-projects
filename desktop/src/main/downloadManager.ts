import { BrowserWindow, type DownloadItem, type Session, type WebContents, shell } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import type { DesktopDownload, FinalizeReason } from '../shared/downloads';
import type { DownloadSettingsStore } from './downloadSettings';
import { DownloadHistoryStore, INTERRUPTED_MESSAGE } from './downloadHistory';
import { DropdownController } from './dropdownController';

function normalizedDestination(value: string): string {
  const resolved = path.resolve(value);
  return process.platform === 'linux' ? resolved : resolved.toLowerCase();
}

function safeFilename(value: string): string {
  const filename = path.basename(value.trim());
  return !filename || filename === '.' || filename === '..' ? 'download' : filename;
}

export function nextAvailableDownloadPath(
  directory: string,
  requestedFilename: string,
  reserved: ReadonlySet<string>,
): string {
  const filename = safeFilename(requestedFilename);
  const parsed = path.parse(filename);
  for (let attempt = 0; attempt < Number.MAX_SAFE_INTEGER; attempt += 1) {
    const suffix = attempt === 0 ? '' : ` (${attempt})`;
    const candidate = path.join(directory, `${parsed.name}${suffix}${parsed.ext}`);
    if (!fs.existsSync(candidate) && !reserved.has(normalizedDestination(candidate))) {
      return candidate;
    }
  }
  throw new Error('Could not choose an available download filename.');
}

function finalize(download: DesktopDownload, reason: FinalizeReason, error?: string): DesktopDownload {
  return {
    ...download,
    bytesPerSecond: 0,
    state: 'finalized',
    finalizeReason: reason,
    finalizedAt: Date.now(),
    error,
  };
}

/**
 * Captures every download from the shared Electron session into the
 * persisted history, and publishes it to the base window (Downloads icon and
 * page) and to the Downloads dropdown.
 */
export class DownloadManager {
  readonly dropdown: DropdownController;

  private readonly history = new DownloadHistoryStore();
  private readonly activeItems = new Map<string, DownloadItem>();
  private readonly reservedDestinations = new Set<string>();
  private disposed = false;

  private readonly willDownload = (_event: Electron.Event, item: DownloadItem): void => {
    this.captureDownload(item);
  };

  constructor(
    private readonly win: BrowserWindow,
    private readonly electronSession: Session,
    private readonly settings: DownloadSettingsStore,
    dropdownUrl: string,
    preloadPath: string,
  ) {
    this.dropdown = new DropdownController(win, () => this.history.all(), dropdownUrl, preloadPath);
    this.electronSession.on('will-download', this.willDownload);
  }

  ownsDropdown(contents: WebContents): boolean {
    return this.dropdown.ownsContents(contents);
  }

  getSnapshot(): DesktopDownload[] {
    return this.history.snapshot();
  }

  /** Ids of completed downloads whose file is no longer on disk. */
  missingFileIds(): string[] {
    return this.history
      .all()
      .filter(
        (download) =>
          download.state === 'finalized' &&
          download.finalizeReason === 'done' &&
          !fs.existsSync(download.savePath),
      )
      .map((download) => download.id);
  }

  cancel(id: string): boolean {
    const download = this.history.get(id);
    const item = this.activeItems.get(id);
    if (!download || !item || download.state !== 'pending') return false;
    this.history.put(finalize(download, 'canceled'));
    this.publish();
    item.cancel();
    return true;
  }

  dismissFromDropdown(id: string): boolean {
    const download = this.history.get(id);
    if (!download || download.state !== 'finalized') return false;
    download.dismissedFromDropdown = true;
    this.history.touch();
    this.dropdown.removeMember(id);
    this.publish();
    return true;
  }

  removeFromHistory(id: string): boolean {
    const download = this.history.get(id);
    if (!download || download.state !== 'finalized') return false;
    this.history.remove(id);
    this.dropdown.removeMember(id);
    this.publish();
    return true;
  }

  clearHistory(): void {
    for (const download of this.history.all()) {
      if (download.state === 'finalized') this.dropdown.removeMember(download.id);
    }
    this.history.clearFinalized();
    this.publish();
  }

  async open(id: string): Promise<string> {
    const download = this.completedDownload(id);
    return shell.openPath(download.savePath);
  }

  showInFolder(id: string): boolean {
    const download = this.completedDownload(id);
    shell.showItemInFolder(download.savePath);
    return true;
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    this.electronSession.off('will-download', this.willDownload);
    // Record downloads cut off by closing the app as interrupted, not as
    // canceled -- the user didn't choose to stop them.
    for (const [id, item] of this.activeItems) {
      const download = this.history.get(id);
      if (download?.state === 'pending') this.history.put(finalize(download, 'failed', INTERRUPTED_MESSAGE));
      item.cancel();
    }
    this.activeItems.clear();
    this.reservedDestinations.clear();
    this.dropdown.dispose();
    await this.history.flush();
  }

  private captureDownload(item: DownloadItem): void {
    const id = randomUUID();
    const filename = safeFilename(item.getFilename());
    let destination = '';
    try {
      const directory = this.settings.getDirectory();
      fs.mkdirSync(directory, { recursive: true });
      destination = nextAvailableDownloadPath(directory, filename, this.reservedDestinations);
      item.setSavePath(destination);
      this.reservedDestinations.add(normalizedDestination(destination));
    } catch (error) {
      console.error(`[DEBUG] failed to start download ${filename}: ${String(error)}`);
      const startedAt = Date.now();
      this.history.put({
        id,
        filename,
        savePath: destination,
        receivedBytes: 0,
        totalBytes: item.getTotalBytes(),
        bytesPerSecond: 0,
        startedAt,
        state: 'finalized',
        finalizeReason: 'failed',
        finalizedAt: startedAt,
        error: `Could not create the download file: ${String(error)}`,
      });
      item.cancel();
      this.dropdown.addDownload(id);
      this.publish();
      return;
    }

    this.history.put({
      id,
      filename: path.basename(destination),
      savePath: destination,
      receivedBytes: item.getReceivedBytes(),
      totalBytes: item.getTotalBytes(),
      bytesPerSecond: 0,
      startedAt: Date.now(),
      state: 'pending',
    });
    this.activeItems.set(id, item);
    this.dropdown.addDownload(id);
    this.publish();

    item.on('updated', (_event, state) => {
      const current = this.history.get(id);
      if (!current || current.state !== 'pending') return;
      current.receivedBytes = item.getReceivedBytes();
      current.totalBytes = item.getTotalBytes();
      current.bytesPerSecond = item.getCurrentBytesPerSecond();
      // An `updated` interruption can be transient. Keep the row pending
      // until DownloadItem emits its terminal `done` state.
      current.error = state === 'interrupted' ? 'Connection interrupted; waiting for Chromium.' : undefined;
      // Progress ticks are not persisted; only structural changes are.
      this.publish();
    });

    item.once('done', (_event, state) => {
      this.activeItems.delete(id);
      this.reservedDestinations.delete(normalizedDestination(destination));
      const current = this.history.get(id);
      // Already finalized: canceled by the user, or interrupted by dispose().
      if (!current || current.state !== 'pending' || this.disposed) return;
      current.receivedBytes = item.getReceivedBytes();
      current.totalBytes = item.getTotalBytes();
      if (state === 'completed') {
        this.history.put(finalize(current, 'done'));
      } else if (state === 'cancelled') {
        this.history.put(finalize(current, 'canceled'));
      } else {
        console.error(`[DEBUG] download interrupted: ${destination}`);
        this.history.put(finalize(current, 'failed', 'The download was interrupted before it completed.'));
      }
      this.publish();
    });
  }

  private completedDownload(id: string): DesktopDownload {
    const download = this.history.get(id);
    if (!download || download.state !== 'finalized' || download.finalizeReason !== 'done') {
      throw new Error('The requested download has not completed.');
    }
    return download;
  }

  private publish(): void {
    if (this.disposed) return;
    this.dropdown.publish();
    if (!this.win.webContents.isDestroyed()) {
      this.win.webContents.send('downloads:update', this.history.snapshot());
    }
  }
}
