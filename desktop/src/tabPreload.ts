import { contextBridge, ipcRenderer } from 'electron';

// Preload for session/dashboard tabs (the React UI served by the SLBP proxy).
// Keep this surface tiny: those pages are web content, so everything exposed
// here is callable by them.
//
// Mirrors `SlbpDesktopApi` in ui/src/types/desktopBridge.d.ts -- the React UI
// detects the desktop app by the presence of `window.slbpDesktop`, so keep
// both declarations in sync.
export interface SlbpDesktopApi {
  /** Open the native folder picker; resolves to a forward-slash path or null on cancel. */
  pickFolder: (initialDir?: string) => Promise<string | null>;
}

const api: SlbpDesktopApi = {
  pickFolder: (initialDir) =>
    ipcRenderer.invoke('tab:pick-folder', typeof initialDir === 'string' ? initialDir : '') as Promise<
      string | null
    >,
};

contextBridge.exposeInMainWorld('slbpDesktop', api);
