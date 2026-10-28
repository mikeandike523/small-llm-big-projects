// API exposed to session/dashboard tabs by the desktop app's tab preload.
//
// Mirrors `SlbpDesktopApi` in desktop/src/tabPreload.ts -- keep both in sync.
// Absent (undefined) whenever the UI runs in a normal browser.
export interface SlbpDesktopApi {
  /** Open the native folder picker; resolves to a forward-slash path or null on cancel. */
  pickFolder: (initialDir?: string) => Promise<string | null>;
}

declare global {
  interface Window {
    slbpDesktop?: SlbpDesktopApi;
  }
}
