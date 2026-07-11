import { contextBridge, ipcRenderer } from 'electron';
import type { TabDescriptor } from './main/tabManager';

export interface TabsUpdatePayload {
  tabs: TabDescriptor[];
  activeId: string | null;
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

// frame: false removes the native titlebar (and its minimize/maximize/close
// buttons) entirely, so the tab-strip UI draws its own and calls back into
// main via these handlers.
contextBridge.exposeInMainWorld('windowAPI', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  close: () => ipcRenderer.invoke('window:close'),
});
