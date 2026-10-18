import { BrowserWindow, type DownloadItem, type Session, WebContentsView, shell } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import type { DesktopDownload } from '../shared/downloads';
import type { DownloadSettingsStore } from './downloadSettings';
import { TAB_STRIP_HEIGHT } from './tabManager';

const OVERLAY_WIDTH = 420;
const OVERLAY_MARGIN = 16;

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

export class DownloadManager {
  readonly view: WebContentsView;

  private readonly downloads = new Map<string, DesktopDownload>();
  private readonly activeItems = new Map<string, DownloadItem>();
  private readonly reservedDestinations = new Set<string>();
  private overlayLoaded = false;
  private requestedHeight = 120;
  private disposed = false;

  private readonly willDownload = (_event: Electron.Event, item: DownloadItem): void => {
    this.captureDownload(item);
  };

  constructor(
    private readonly win: BrowserWindow,
    private readonly electronSession: Session,
    private readonly settings: DownloadSettingsStore,
    overlayUrl: string,
    preloadPath: string,
  ) {
    this.view = new WebContentsView({
      webPreferences: {
        preload: preloadPath,
        contextIsolation: true,
        sandbox: true,
        backgroundThrottling: false,
      },
    });
    this.view.setBackgroundColor('#00000000');
    this.view.setVisible(false);
    this.win.contentView.addChildView(this.view);
    this.view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    this.view.webContents.on('did-finish-load', () => {
      this.overlayLoaded = true;
      this.publish();
    });
    this.view.webContents.on('render-process-gone', (_event, details) => {
      console.error(`[DEBUG] download overlay renderer exited: ${details.reason}`);
    });
    void this.view.webContents.loadURL(overlayUrl);

    this.electronSession.on('will-download', this.willDownload);
    this.win.on('resize', this.layout);
  }

  ownsSender(senderId: number): boolean {
    return !this.view.webContents.isDestroyed() && this.view.webContents.id === senderId;
  }

  getSnapshot(): DesktopDownload[] {
    return Array.from(this.downloads.values(), (download) => ({ ...download }));
  }

  bringToFront(): void {
    if (this.disposed) return;
    this.win.contentView.addChildView(this.view);
  }

  setOverlayHeight(height: number): void {
    if (!Number.isFinite(height)) return;
    this.requestedHeight = Math.max(0, Math.ceil(height));
    this.layout();
  }

  cancel(id: string): boolean {
    const download = this.downloads.get(id);
    const item = this.activeItems.get(id);
    if (!download || !item || download.state !== 'progressing') return false;
    download.state = 'cancelled';
    download.error = undefined;
    this.publish();
    item.cancel();
    return true;
  }

  dismiss(id: string): boolean {
    const download = this.downloads.get(id);
    if (!download || download.state === 'progressing') return false;
    this.downloads.delete(id);
    this.publish();
    return true;
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

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.electronSession.off('will-download', this.willDownload);
    this.win.off('resize', this.layout);
    for (const item of this.activeItems.values()) item.cancel();
    this.activeItems.clear();
    this.reservedDestinations.clear();
    this.win.contentView.removeChildView(this.view);
    if (!this.view.webContents.isDestroyed()) this.view.webContents.close();
  }

  private readonly layout = (): void => {
    if (this.disposed || this.downloads.size === 0 || this.requestedHeight <= 0) {
      this.view.setVisible(false);
      return;
    }
    const bounds = this.win.getContentBounds();
    const width = Math.max(0, Math.min(OVERLAY_WIDTH, bounds.width - OVERLAY_MARGIN * 2));
    const maxHeight = Math.max(0, bounds.height - TAB_STRIP_HEIGHT - OVERLAY_MARGIN * 2);
    const height = Math.min(this.requestedHeight, maxHeight);
    if (width === 0 || height === 0) {
      this.view.setVisible(false);
      return;
    }
    this.view.setBounds({
      x: bounds.width - width - OVERLAY_MARGIN,
      y: bounds.height - height - OVERLAY_MARGIN,
      width,
      height,
    });
    this.view.setVisible(true);
  };

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
      this.downloads.set(id, {
        id,
        filename,
        savePath: destination,
        receivedBytes: 0,
        totalBytes: item.getTotalBytes(),
        bytesPerSecond: 0,
        state: 'failed',
        startedAt: Date.now(),
        error: `Could not create the download file: ${String(error)}`,
      });
      item.cancel();
      this.publish();
      return;
    }

    const download: DesktopDownload = {
      id,
      filename: path.basename(destination),
      savePath: destination,
      receivedBytes: item.getReceivedBytes(),
      totalBytes: item.getTotalBytes(),
      bytesPerSecond: 0,
      state: 'progressing',
      startedAt: Date.now(),
    };
    this.downloads.set(id, download);
    this.activeItems.set(id, item);
    this.publish();

    item.on('updated', (_event, state) => {
      const current = this.downloads.get(id);
      if (!current || current.state === 'cancelled') return;
      current.receivedBytes = item.getReceivedBytes();
      current.totalBytes = item.getTotalBytes();
      current.bytesPerSecond = item.getCurrentBytesPerSecond();
      // An `updated` interruption can be transient. Keep the row active until
      // DownloadItem emits its terminal `done` state.
      current.error = state === 'interrupted' ? 'Connection interrupted; waiting for Chromium.' : undefined;
      this.publish();
    });

    item.once('done', (_event, state) => {
      this.activeItems.delete(id);
      this.reservedDestinations.delete(normalizedDestination(destination));
      const current = this.downloads.get(id);
      if (!current) return;
      current.receivedBytes = item.getReceivedBytes();
      current.totalBytes = item.getTotalBytes();
      current.bytesPerSecond = 0;
      if (state === 'completed') {
        current.state = 'completed';
        current.error = undefined;
      } else if (current.state === 'cancelled' || state === 'cancelled') {
        current.state = 'cancelled';
        current.error = undefined;
      } else {
        current.state = 'failed';
        current.error = 'The download was interrupted before it completed.';
        console.error(`[DEBUG] download interrupted: ${destination}`);
      }
      this.publish();
    });
  }

  private completedDownload(id: string): DesktopDownload {
    const download = this.downloads.get(id);
    if (!download || download.state !== 'completed') {
      throw new Error('The requested download has not completed.');
    }
    return download;
  }

  private publish(): void {
    if (this.downloads.size === 0) {
      this.view.setVisible(false);
    } else {
      // The empty overlay reports zero height. Give the first subsequent row
      // enough space to render and report its exact content height.
      if (this.requestedHeight <= 0) this.requestedHeight = 120;
      this.layout();
    }
    if (!this.overlayLoaded || this.view.webContents.isDestroyed()) return;
    this.view.webContents.send('downloads:update', this.getSnapshot());
  }
}
