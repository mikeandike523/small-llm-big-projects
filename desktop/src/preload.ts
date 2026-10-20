import { contextBridge, ipcRenderer } from 'electron';
import type { TabsUpdatePayload } from './main/tabManager';
import type { OverlayId } from './shared/tabSelection';
import type { HealthStatus } from './main/serverLauncher';
import type { DesktopDownload, DownloadSettingsSnapshot, DropdownAnchor } from './shared/downloads';

export type { TabsUpdatePayload };

export interface HealthSnapshot {
  status: HealthStatus;
  lines: string[];
  logPath: string;
}

contextBridge.exposeInMainWorld('tabsAPI', {
  onUpdate: (callback: (payload: TabsUpdatePayload) => void) => {
    ipcRenderer.on('tabs:update', (_event, payload: TabsUpdatePayload) =>
      callback(payload),
    );
  },
  switchTab: (id: string) => ipcRenderer.invoke('tabs:switch', id),
  closeTab: (id: string) => ipcRenderer.invoke('tabs:close', id),
  toggleOverlay: (id: OverlayId) => ipcRenderer.invoke('tabs:toggle-overlay', id),
});

contextBridge.exposeInMainWorld('healthAPI', {
  onStatus: (callback: (status: HealthStatus) => void) => {
    ipcRenderer.on('health:status', (_event, status: HealthStatus) => callback(status));
  },
  onLogLines: (callback: (lines: string[]) => void) => {
    ipcRenderer.on('health:log-lines', (_event, lines: string[]) => callback(lines));
  },
  getSnapshot: (): Promise<HealthSnapshot> => ipcRenderer.invoke('health:get-snapshot'),
  openDashboard: () => ipcRenderer.invoke('health:open-dashboard'),
  restartServer: () => ipcRenderer.invoke('health:restart-server'),
});

contextBridge.exposeInMainWorld('settingsAPI', {
  getDownloads: () => ipcRenderer.invoke('settings:get-downloads') as Promise<DownloadSettingsSnapshot>,
  chooseDownloads: () => ipcRenderer.invoke('settings:choose-downloads') as Promise<DownloadSettingsSnapshot>,
  resetDownloads: () => ipcRenderer.invoke('settings:reset-downloads') as Promise<DownloadSettingsSnapshot>,
});

// The Downloads icon (progress ring/badge) and the Downloads page.
contextBridge.exposeInMainWorld('downloadsAPI', {
  getSnapshot: () => ipcRenderer.invoke('downloads:get-snapshot') as Promise<DesktopDownload[]>,
  onUpdate: (callback: (downloads: DesktopDownload[]) => void) => {
    ipcRenderer.on('downloads:update', (_event, downloads: DesktopDownload[]) => callback(downloads));
  },
  setDropdownAnchor: (anchor: DropdownAnchor) => ipcRenderer.send('downloads:set-dropdown-anchor', anchor),
  cancel: (id: string) => ipcRenderer.invoke('downloads:cancel', id) as Promise<boolean>,
  open: (id: string) => ipcRenderer.invoke('downloads:open', id) as Promise<string>,
  showInFolder: (id: string) => ipcRenderer.invoke('downloads:show-in-folder', id) as Promise<boolean>,
  removeFromHistory: (id: string) => ipcRenderer.invoke('downloads:remove-from-history', id) as Promise<boolean>,
  clearHistory: () => ipcRenderer.invoke('downloads:clear-history') as Promise<void>,
  getMissingFileIds: () => ipcRenderer.invoke('downloads:get-missing-file-ids') as Promise<string[]>,
});

contextBridge.exposeInMainWorld('processDoctorAPI', {
  start: (cols: number, rows: number) =>
    ipcRenderer.invoke('process-doctor:start', { cols, rows }) as Promise<void>,
  write: (data: string) => ipcRenderer.send('process-doctor:input', data),
  resize: (cols: number, rows: number) =>
    ipcRenderer.send('process-doctor:resize', { cols, rows }),
  stop: () => ipcRenderer.invoke('process-doctor:stop') as Promise<void>,
  onData: (callback: (data: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, data: string) => callback(data);
    ipcRenderer.on('process-doctor:data', listener);
    return () => ipcRenderer.removeListener('process-doctor:data', listener);
  },
  onExit: (callback: (exitCode: number) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, exitCode: number) => callback(exitCode);
    ipcRenderer.on('process-doctor:exit', listener);
    return () => ipcRenderer.removeListener('process-doctor:exit', listener);
  },
});

// Desktop-app release notes, read from disk in the main process
// (desktop/desktop-release-notes/, produced by release_manager.py).
contextBridge.exposeInMainWorld('changelogAPI', {
  getVersion: () => ipcRenderer.invoke('changelog:get-version') as Promise<string>,
  getIndex: () => ipcRenderer.invoke('changelog:get-index'),
  getNote: (version: string) => ipcRenderer.invoke('changelog:get-note', version) as Promise<string | null>,
});

// frame: false removes the native titlebar (and its minimize/maximize/close
// buttons) entirely, so the tab-strip UI draws its own and calls back into
// main via these handlers.
contextBridge.exposeInMainWorld('windowAPI', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  close: () => ipcRenderer.invoke('window:close'),
});
