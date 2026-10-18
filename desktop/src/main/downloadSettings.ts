import { app } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import type { DownloadSettingsSnapshot } from '../shared/downloads';

interface PersistedDesktopSettings {
  downloadsDirectory?: string;
}

export class DownloadSettingsStore {
  private readonly settingsFile: string;
  private downloadsDirectory: string | null = null;

  constructor() {
    this.settingsFile = path.join(app.getPath('userData'), 'desktop-settings.json');
    this.load();
  }

  getDirectory(): string {
    return this.downloadsDirectory ?? app.getPath('downloads');
  }

  getSnapshot(): DownloadSettingsSnapshot {
    const defaultDirectory = app.getPath('downloads');
    return {
      directory: this.downloadsDirectory ?? defaultDirectory,
      defaultDirectory,
      usesDefault: this.downloadsDirectory === null,
    };
  }

  setDirectory(directory: string): DownloadSettingsSnapshot {
    const resolved = path.resolve(directory);
    const info = fs.statSync(resolved);
    if (!info.isDirectory()) {
      throw new Error('The selected download destination is not a directory.');
    }
    this.downloadsDirectory = resolved;
    this.persist();
    return this.getSnapshot();
  }

  resetDirectory(): DownloadSettingsSnapshot {
    this.downloadsDirectory = null;
    this.persist();
    return this.getSnapshot();
  }

  private load(): void {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.settingsFile, 'utf8')) as PersistedDesktopSettings;
      if (typeof parsed.downloadsDirectory === 'string' && parsed.downloadsDirectory.trim()) {
        this.downloadsDirectory = path.resolve(parsed.downloadsDirectory);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        console.error(`[DEBUG] failed to read desktop settings: ${String(error)}`);
      }
    }
  }

  private persist(): void {
    const settings: PersistedDesktopSettings = {};
    if (this.downloadsDirectory) {
      settings.downloadsDirectory = this.downloadsDirectory;
    }
    fs.writeFileSync(this.settingsFile, JSON.stringify(settings, null, 2));
  }
}
