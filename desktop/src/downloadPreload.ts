import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopDownload } from './shared/downloads';

contextBridge.exposeInMainWorld('downloadsAPI', {
  getSnapshot: () => ipcRenderer.invoke('downloads:get-snapshot') as Promise<DesktopDownload[]>,
  onUpdate: (callback: (downloads: DesktopDownload[]) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, downloads: DesktopDownload[]) => callback(downloads);
    ipcRenderer.on('downloads:update', listener);
    return () => ipcRenderer.removeListener('downloads:update', listener);
  },
  setOverlayHeight: (height: number) => ipcRenderer.send('downloads:set-overlay-height', height),
  cancel: (id: string) => ipcRenderer.invoke('downloads:cancel', id) as Promise<boolean>,
  dismiss: (id: string) => ipcRenderer.invoke('downloads:dismiss', id) as Promise<boolean>,
  open: (id: string) => ipcRenderer.invoke('downloads:open', id) as Promise<string>,
  showInFolder: (id: string) => ipcRenderer.invoke('downloads:show-in-folder', id) as Promise<boolean>,
});
