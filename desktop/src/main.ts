import { app, BrowserWindow, dialog, ipcMain, session } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import started from 'electron-squirrel-startup';
import { resolveRepoRoot } from './main/repoRoot';
import { startControlServer, type ControlServerHandle } from './main/controlServer';
import { TabManager } from './main/tabManager';
import { startServerLifecycle, type HealthStatus, type ServerLifecycleHandle } from './main/serverLauncher';
import { getCurrentVersion, readIndex, readNote } from './main/changelog';
import { ProcessDoctorTerminal } from './main/processDoctor';
import { DownloadManager } from './main/downloadManager';
import { DownloadSettingsStore } from './main/downloadSettings';
import type { DropdownAnchor } from './shared/downloads';
import { isOverlayId } from './shared/tabSelection';

if (started) {
  app.quit();
}

// Racing `slbp session new` calls can both decide to spawn before either sees a
// running control server; Electron's single-instance lock collapses that down to
// one real instance, and each CLI invocation's own health-check poll converges on it.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

/**
 * Bring an already-running app's window to the foreground. Windows'
 * foreground-lock can silently swallow a plain show()+focus() call when it
 * comes from a background process (this app reacting to an HTTP request
 * from the CLI, not real user input) rather than raising an error -- the
 * window just stays behind whatever currently has focus. Briefly toggling
 * alwaysOnTop forces a SetWindowPos(HWND_TOPMOST), which isn't subject to
 * that restriction, so show()/focus() reliably take effect afterward.
 */
function bringToFront(win: BrowserWindow): void {
  if (win.isMinimized()) {
    win.restore();
  }
  win.setAlwaysOnTop(true);
  win.show();
  win.focus();
  win.setAlwaysOnTop(false);
}

let currentWindow: BrowserWindow | null = null;
let tabManager: TabManager | null = null;
let controlServerHandle: ControlServerHandle | null = null;
let serverLifecycleHandle: ServerLifecycleHandle | null = null;
let currentProxyOrigin: string | null = null;
let downloadManager: DownloadManager | null = null;
let downloadSettings: DownloadSettingsStore | null = null;
const processDoctorTerminal = new ProcessDoctorTerminal();

// Registered once at module scope (not inside createWindow) so a macOS
// activate-with-no-windows recreate doesn't try to register the same
// ipcMain channel twice, which throws.
ipcMain.handle('window:minimize', () => currentWindow?.minimize());
ipcMain.handle('window:toggle-maximize', () =>
  currentWindow?.isMaximized() ? currentWindow.unmaximize() : currentWindow?.maximize(),
);
ipcMain.handle('window:close', () => currentWindow?.close());
ipcMain.handle('tabs:switch', (_event, id: string) => tabManager?.switchTo(id));
ipcMain.handle('tabs:close', (_event, id: string) => tabManager?.closeTabById(id));
ipcMain.handle('tabs:toggle-overlay', (_event, id: unknown) => {
  if (isOverlayId(id)) tabManager?.toggleOverlay(id);
});
ipcMain.handle('health:get-snapshot', () => serverLifecycleHandle?.getSnapshot());
ipcMain.handle('health:restart-server', () => serverLifecycleHandle?.restart());
ipcMain.handle('health:open-dashboard', () => {
  if (currentProxyOrigin) {
    tabManager?.openDashboard(currentProxyOrigin);
  }
});
ipcMain.handle('process-doctor:start', (event, size: { cols: number; rows: number }) => {
  const repoRoot = resolveRepoRoot();
  processDoctorTerminal.start(
    repoRoot,
    {
      onData: (data) => {
        if (!event.sender.isDestroyed()) event.sender.send('process-doctor:data', data);
      },
      onExit: (exitCode) => {
        if (!event.sender.isDestroyed()) event.sender.send('process-doctor:exit', exitCode);
      },
    },
    size.cols,
    size.rows,
  );
});
ipcMain.on('process-doctor:input', (_event, data: string) => processDoctorTerminal.write(data));
ipcMain.on('process-doctor:resize', (_event, size: { cols: number; rows: number }) =>
  processDoctorTerminal.resize(size.cols, size.rows),
);
ipcMain.handle('process-doctor:stop', () => processDoctorTerminal.stop());

// Desktop-app release notes (release_manager.py output). Registered at module
// scope like the other handlers so a macOS activate-with-no-windows recreate
// can't register the same channel twice.
ipcMain.handle('changelog:get-version', () => getCurrentVersion());
ipcMain.handle('changelog:get-index', () => readIndex());
ipcMain.handle('changelog:get-note', (_event, version: string) => readNote(version));

function downloadManagerForDropdown(sender: Electron.WebContents): DownloadManager | null {
  return downloadManager?.ownsDropdown(sender) ? downloadManager : null;
}

function downloadManagerForBase(senderId: number): DownloadManager | null {
  return isBaseRenderer(senderId) ? downloadManager : null;
}

/** Calls from the dropdown view or the base window (Downloads icon and page). */
function downloadManagerForEither(event: Electron.IpcMainInvokeEvent): DownloadManager {
  const manager = downloadManagerForDropdown(event.sender) ?? downloadManagerForBase(event.sender.id);
  if (!manager) throw new Error('Download manager is unavailable.');
  return manager;
}

// Every webContents (base window, tab views, the dropdown itself) reports its
// mouse-downs so the dropdown can close on a click anywhere else.
app.on('web-contents-created', (_event, contents) => {
  contents.on('input-event', (_inputEvent, input) => {
    downloadManager?.dropdown.handleInput(contents, input);
  });
});

ipcMain.handle('downloads:get-snapshot', (event) => downloadManagerForEither(event).getSnapshot());
ipcMain.handle('downloads:cancel', (event, id: string) => downloadManagerForEither(event).cancel(id));
ipcMain.handle('downloads:open', (event, id: string) => downloadManagerForEither(event).open(id));
ipcMain.handle('downloads:show-in-folder', (event, id: string) => downloadManagerForEither(event).showInFolder(id));

// Dropdown view only.
ipcMain.on('dropdown:set-height', (event, height: number) => {
  downloadManagerForDropdown(event.sender)?.dropdown.setHeight(height);
});
ipcMain.on('dropdown:closed', (event) => downloadManagerForDropdown(event.sender)?.dropdown.finishClose());
ipcMain.on('dropdown:auto-hide', (event) => downloadManagerForDropdown(event.sender)?.dropdown.close());
ipcMain.handle(
  'dropdown:dismiss',
  (event, id: string) => downloadManagerForDropdown(event.sender)?.dismissFromDropdown(id) ?? false,
);
ipcMain.handle('dropdown:view-all', (event) => {
  const manager = downloadManagerForDropdown(event.sender);
  if (!manager) return;
  manager.dropdown.close();
  // Opens, never toggles: "View all" must not close an open Downloads page.
  tabManager?.openOverlay('downloads');
});

// Base window only (Downloads icon and page).
ipcMain.on('downloads:set-dropdown-anchor', (event, anchor: DropdownAnchor) => {
  downloadManagerForBase(event.sender.id)?.dropdown.setAnchor(anchor);
});
ipcMain.handle(
  'downloads:remove-from-history',
  (event, id: string) => downloadManagerForBase(event.sender.id)?.removeFromHistory(id) ?? false,
);
ipcMain.handle('downloads:clear-history', (event) => downloadManagerForBase(event.sender.id)?.clearHistory());
ipcMain.handle(
  'downloads:get-missing-file-ids',
  (event) => downloadManagerForBase(event.sender.id)?.missingFileIds() ?? [],
);

function isBaseRenderer(senderId: number): boolean {
  return currentWindow?.webContents.id === senderId;
}

// Session/dashboard tabs only (tabPreload.ts): the New Session dialog's native
// folder picker. The desktop app always runs its own local server, so a folder
// chosen here is valid on the server too.
ipcMain.handle('tab:pick-folder', async (event, initialDir: unknown) => {
  if (!currentWindow || !tabManager?.ownsTabWebContents(event.sender.id)) {
    throw new Error('Folder picker is unavailable.');
  }
  const start = typeof initialDir === 'string' && initialDir.trim() ? initialDir : app.getPath('home');
  const result = await dialog.showOpenDialog(currentWindow, {
    title: 'Select working directory',
    defaultPath: fs.existsSync(start) ? start : app.getPath('home'),
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  return result.filePaths[0].replace(/\\/g, '/');
});

ipcMain.handle('settings:get-downloads', (event) => {
  if (!isBaseRenderer(event.sender.id)) throw new Error('Settings are unavailable.');
  return downloadSettings?.getSnapshot();
});
ipcMain.handle('settings:choose-downloads', async (event) => {
  if (!isBaseRenderer(event.sender.id) || !currentWindow || !downloadSettings) {
    throw new Error('Settings are unavailable.');
  }
  const result = await dialog.showOpenDialog(currentWindow, {
    title: 'Choose download folder',
    defaultPath: downloadSettings.getDirectory(),
    properties: ['openDirectory', 'createDirectory'],
  });
  if (!result.canceled && result.filePaths[0]) {
    return downloadSettings.setDirectory(result.filePaths[0]);
  }
  return downloadSettings.getSnapshot();
});
ipcMain.handle('settings:reset-downloads', (event) => {
  if (!isBaseRenderer(event.sender.id) || !downloadSettings) {
    throw new Error('Settings are unavailable.');
  }
  return downloadSettings.resetDirectory();
});

const createWindow = () => {
  const mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  currentWindow = mainWindow;
  console.log(`[DEBUG] window created at ${Date.now()}`);

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`),
    );
  }

  tabManager = new TabManager(
    mainWindow,
    {
      onChildViewAdded: () => downloadManager?.dropdown.bringToFront(),
      // The Downloads page already lists new downloads; the dropdown would be redundant.
      onOverlayChanged: (overlay) => {
        if (overlay === 'downloads') downloadManager?.dropdown.close();
      },
    },
    path.join(__dirname, 'tabPreload.js'),
  );
  downloadSettings = new DownloadSettingsStore();
  const dropdownUrl = MAIN_WINDOW_VITE_DEV_SERVER_URL
    ? new URL('/download-dropdown.html', MAIN_WINDOW_VITE_DEV_SERVER_URL).toString()
    : pathToFileURL(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/download-dropdown.html`)).toString();
  downloadManager = new DownloadManager(
    mainWindow,
    session.defaultSession,
    downloadSettings,
    dropdownUrl,
    path.join(__dirname, 'downloadPreload.js'),
    () => tabManager?.currentOverlay === 'downloads',
  );
  let tabViewsDisposed = false;
  mainWindow.on('close', (event) => {
    processDoctorTerminal.stop();
    if (tabViewsDisposed) return;
    event.preventDefault();
    const disposeDownloads = downloadManager?.dispose() ?? Promise.resolve();
    downloadManager = null;
    downloadSettings = null;
    const disposeTabs = tabManager?.dispose() ?? Promise.resolve();
    void Promise.allSettled([disposeDownloads, disposeTabs]).finally(() => {
      tabViewsDisposed = true;
      tabManager = null;
      mainWindow.close();
    });
  });
  mainWindow.on('closed', () => {
    if (currentWindow === mainWindow) {
      currentWindow = null;
    }
  });

  const repoRoot = resolveRepoRoot();

  serverLifecycleHandle = startServerLifecycle(repoRoot, {
    onStatus: (status: HealthStatus) => {
      console.log(`[DEBUG] health status: ${status.kind}${status.detail ? ` (${status.detail})` : ''} at ${Date.now()}`);
      if (status.state) {
        currentProxyOrigin = `http://localhost:${status.state.proxy_port}`;
      }
      mainWindow.webContents.send('health:status', status);
    },
    onLog: (lines: string[]) => {
      mainWindow.webContents.send('health:log-lines', lines);
    },
  });

  controlServerHandle = startControlServer(repoRoot, (payload) => {
    bringToFront(mainWindow);
    if (payload.dashboard) {
      tabManager?.openDashboard(payload.proxyOrigin);
    } else if (payload.sessionId) {
      tabManager?.openSession(payload.sessionId, payload.proxyOrigin);
    }
  });

  mainWindow.webContents.once('did-finish-load', () => {
    tabManager?.restore();
  });
};

app.on('ready', createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('before-quit', () => {
  processDoctorTerminal.stop();
  controlServerHandle?.cleanup();
});
