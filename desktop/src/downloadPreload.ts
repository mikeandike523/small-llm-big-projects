import { contextBridge, ipcRenderer } from 'electron';
import type { DropdownState } from './shared/downloads';

function subscribe<T>(channel: string, callback: (payload: T) => void): () => void {
  const listener = (_event: Electron.IpcRendererEvent, payload: T) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('dropdownAPI', {
  onUpdate: (callback: (state: DropdownState) => void) => subscribe('dropdown:update', callback),
  onOpened: (callback: () => void) => subscribe('dropdown:opened', callback),
  onClosing: (callback: () => void) => subscribe('dropdown:closing', callback),
  onMaxHeight: (callback: (height: number) => void) => subscribe('dropdown:max-height', callback),
  notifyClosed: () => ipcRenderer.send('dropdown:closed'),
  setHeight: (height: number) => ipcRenderer.send('dropdown:set-height', height),
  cancel: (id: string) => ipcRenderer.invoke('downloads:cancel', id) as Promise<boolean>,
  dismiss: (id: string) => ipcRenderer.invoke('dropdown:dismiss', id) as Promise<boolean>,
  open: (id: string) => ipcRenderer.invoke('downloads:open', id) as Promise<string>,
  showInFolder: (id: string) => ipcRenderer.invoke('downloads:show-in-folder', id) as Promise<boolean>,
  viewAll: () => ipcRenderer.invoke('dropdown:view-all') as Promise<void>,
});
