import { app, BrowserWindow, dialog, ipcMain, session } from 'electron';
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

function downloadManagerForSender(senderId: number): DownloadManager | null {
  return downloadManager?.ownsSender(senderId) ? downloadManager : null;
}

ipcMain.handle('downloads:get-snapshot', (event) => downloadManagerForSender(event.sender.id)?.getSnapshot() ?? []);
ipcMain.on('downloads:set-overlay-height', (event, height: number) => {
  downloadManagerForSender(event.sender.id)?.setOverlayHeight(height);
});
ipcMain.handle(
  'downloads:cancel',
  (event, id: string) => downloadManagerForSender(event.sender.id)?.cancel(id) ?? false,
);
ipcMain.handle(
  'downloads:dismiss',
  (event, id: string) => downloadManagerForSender(event.sender.id)?.dismiss(id) ?? false,
);
ipcMain.handle('downloads:open', (event, id: string) => {
  const manager = downloadManagerForSender(event.sender.id);
  if (!manager) throw new Error('Download manager is unavailable.');
  return manager.open(id);
});
ipcMain.handle(
  'downloads:show-in-folder',
  (event, id: string) => downloadManagerForSender(event.sender.id)?.showInFolder(id) ?? false,
);

function isBaseRenderer(senderId: number): boolean {
  return currentWindow?.webContents.id === senderId;
}

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

  tabManager = new TabManager(mainWindow, () => downloadManager?.bringToFront());
  downloadSettings = new DownloadSettingsStore();
  const overlayUrl = MAIN_WINDOW_VITE_DEV_SERVER_URL
    ? new URL('/download-overlay.html', MAIN_WINDOW_VITE_DEV_SERVER_URL).toString()
    : pathToFileURL(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/download-overlay.html`)).toString();
  downloadManager = new DownloadManager(
    mainWindow,
    session.defaultSession,
    downloadSettings,
    overlayUrl,
    path.join(__dirname, 'downloadPreload.js'),
  );
  let tabViewsDisposed = false;
  mainWindow.on('close', (event) => {
    processDoctorTerminal.stop();
    if (tabViewsDisposed) return;
    event.preventDefault();
    downloadManager?.dispose();
    downloadManager = null;
    downloadSettings = null;
    const disposeTabs = tabManager?.dispose() ?? Promise.resolve();
    void disposeTabs.finally(() => {
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
