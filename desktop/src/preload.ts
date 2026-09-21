import { contextBridge, ipcRenderer } from 'electron';
import type { TabDescriptor } from './main/tabManager';
import type { HealthStatus } from './main/serverLauncher';

export interface TabsUpdatePayload {
  tabs: TabDescriptor[];
  activeId: string | null;
}

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
