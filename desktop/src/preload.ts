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

// frame: false removes the native titlebar (and its minimize/maximize/close
// buttons) entirely, so the tab-strip UI draws its own and calls back into
// main via these handlers.
contextBridge.exposeInMainWorld('windowAPI', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  close: () => ipcRenderer.invoke('window:close'),
});
