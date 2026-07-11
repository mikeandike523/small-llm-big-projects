import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'node:path';
import started from 'electron-squirrel-startup';
import { resolveRepoRoot } from './main/repoRoot';
import { startControlServer, type ControlServerHandle } from './main/controlServer';
import { TabManager } from './main/tabManager';

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

let currentWindow: BrowserWindow | null = null;
let tabManager: TabManager | null = null;
let controlServerHandle: ControlServerHandle | null = null;

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

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`),
    );
  }

  tabManager = new TabManager(mainWindow);

  const repoRoot = resolveRepoRoot();
  controlServerHandle = startControlServer(repoRoot, (payload) => {
    mainWindow.show();
    mainWindow.focus();
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
  controlServerHandle?.cleanup();
});
