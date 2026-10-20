import { app } from 'electron';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import type { DesktopDownload } from '../shared/downloads';

/** History beyond this many entries drops the oldest (by start time). */
export const MAX_DOWNLOAD_HISTORY = 500;

export const INTERRUPTED_MESSAGE = 'Interrupted (app closed)';

interface PersistedHistory {
  downloads: DesktopDownload[];
}

function isDownload(value: unknown): value is DesktopDownload {
  const candidate = value as Partial<DesktopDownload> | null;
  return (
    typeof candidate === 'object' &&
    candidate !== null &&
    typeof candidate.id === 'string' &&
    typeof candidate.filename === 'string' &&
    typeof candidate.startedAt === 'number' &&
    (candidate.state === 'pending' || candidate.state === 'finalized')
  );
}

/**
 * The single persisted record of desktop downloads, backing both the
 * Downloads page and the titlebar dropdown. Entries are only ever removed by
 * the page's "Remove from history" / "Clear history" (or the size cap).
 */
export class DownloadHistoryStore {
  private readonly file: string;
  private readonly downloads = new Map<string, DesktopDownload>();
  private persistTimer: NodeJS.Timeout | null = null;
  private pendingJson: string | null = null;
  private persistWrite: Promise<void> = Promise.resolve();

  constructor() {
    this.file = path.join(app.getPath('userData'), 'downloads-history.json');
    this.load();
  }

  get(id: string): DesktopDownload | undefined {
    return this.downloads.get(id);
  }

  all(): DesktopDownload[] {
    return Array.from(this.downloads.values());
  }

  snapshot(): DesktopDownload[] {
    return this.all().map((download) => ({ ...download }));
  }

  /** Insert or replace an entry and persist. */
  put(download: DesktopDownload): void {
    this.downloads.set(download.id, download);
    this.enforceCap();
    this.persist();
  }

  /** Persist after an in-place structural change to an existing entry. */
  touch(): void {
    this.persist();
  }

  remove(id: string): boolean {
    const removed = this.downloads.delete(id);
    if (removed) this.persist();
    return removed;
  }

  /** Remove every finalized entry; pending downloads are still running. */
  clearFinalized(): void {
    for (const download of this.all()) {
      if (download.state === 'finalized') this.downloads.delete(download.id);
    }
    this.persist();
  }

  async flush(): Promise<void> {
    if (this.persistTimer) {
      clearTimeout(this.persistTimer);
      this.persistTimer = null;
    }
    while (this.pendingJson) {
      const json = this.pendingJson;
      this.pendingJson = null;
      this.persistWrite = this.persistWrite
        .then(() => fsp.writeFile(this.file, json))
        .catch((error) => {
          console.error(`[DEBUG] failed to persist download history: ${String(error)}`);
        });
      await this.persistWrite;
    }
    await this.persistWrite;
  }

  private load(): void {
    let parsed: PersistedHistory | null = null;
    try {
      parsed = JSON.parse(fs.readFileSync(this.file, 'utf8')) as PersistedHistory;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        console.error(`[DEBUG] failed to read download history: ${String(error)}`);
      }
      return;
    }
    let repaired = false;
    for (const entry of Array.isArray(parsed?.downloads) ? parsed.downloads : []) {
      if (!isDownload(entry)) continue;
      if (entry.state === 'pending') {
        // Nothing can still be downloading at startup -- the DownloadItem died
        // with the previous process.
        this.downloads.set(entry.id, {
          ...entry,
          bytesPerSecond: 0,
          state: 'finalized',
          finalizeReason: 'failed',
          finalizedAt: Date.now(),
          error: INTERRUPTED_MESSAGE,
        });
        repaired = true;
      } else {
        this.downloads.set(entry.id, entry);
      }
    }
    if (this.enforceCap() || repaired) this.persist();
  }

  private enforceCap(): boolean {
    if (this.downloads.size <= MAX_DOWNLOAD_HISTORY) return false;
    const oldestFirst = this.all().sort((a, b) => a.startedAt - b.startedAt);
    for (const download of oldestFirst.slice(0, this.downloads.size - MAX_DOWNLOAD_HISTORY)) {
      this.downloads.delete(download.id);
    }
    return true;
  }

  private persist(): void {
    const data: PersistedHistory = { downloads: this.all() };
    this.pendingJson = JSON.stringify(data, null, 2);
    if (this.persistTimer) clearTimeout(this.persistTimer);
    this.persistTimer = setTimeout(() => {
      this.persistTimer = null;
      void this.flush();
    }, 250);
  }
}
