import type { DesktopDownload, DropdownAnchor } from '../shared/downloads';

// Exposed by preload.ts to the base window (Downloads icon and page).
declare global {
  interface Window {
    downloadsAPI: {
      getSnapshot: () => Promise<DesktopDownload[]>;
      onUpdate: (callback: (downloads: DesktopDownload[]) => void) => void;
      toggleDropdown: () => Promise<void>;
      setDropdownAnchor: (anchor: DropdownAnchor) => void;
      cancel: (id: string) => Promise<boolean>;
      open: (id: string) => Promise<string>;
      showInFolder: (id: string) => Promise<boolean>;
      removeFromHistory: (id: string) => Promise<boolean>;
      clearHistory: () => Promise<void>;
      getMissingFileIds: () => Promise<string[]>;
    };
  }
}

export {};
