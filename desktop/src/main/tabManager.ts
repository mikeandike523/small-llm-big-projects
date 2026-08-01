import { app, BrowserWindow, WebContentsView, shell } from 'electron';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';

export const TAB_STRIP_HEIGHT = 40;

export type TabKind = 'session' | 'dashboard' | 'health';

interface TabRecord {
  id: string;
  kind: TabKind;
  sessionId?: string;
  proxyOrigin: string;
  label: string;
  // For dashboard tabs we persist the exact URL the user is on (e.g. after
  // starting a session from the dashboard). Session tabs are always resumed at
  // their canonical session URL.
  currentUrl?: string;
  // null only for the health tab, which is rendered by the base window's own
  // page rather than a WebContentsView (the backend may not exist yet).
  view: WebContentsView | null;
}

export interface TabDescriptor {
  id: string;
  kind: TabKind;
  label: string;
}

interface PersistedTab {
  kind: TabKind;
  sessionId?: string;
  proxyOrigin: string;
  // Present for dashboard tabs so that e.g. a dashboard that spawned a new
  // session can be restored to that exact session view.
  currentUrl?: string;
}

interface PersistedState {
  tabs: PersistedTab[];
  activeId?: string;
}

function urlFor(kind: TabKind, proxyOrigin: string, sessionId?: string): string {
  return kind === 'dashboard'
    ? `${proxyOrigin}/`
    : `${proxyOrigin}/session?sessionId=${sessionId}`;
}

/**
 * Owns every open tab as a WebContentsView composited into the BrowserWindow's
 * contentView, below a fixed-height strip reserved for our own tab-bar UI.
 * Session/dashboard tabs stay attached while inactive and are hidden/shown on
 * switch, so their renderers stay warm without paying native view attach costs
 * on every tab change. Tabs are persisted to disk so a relaunch can restore them.
 */
export class TabManager {
  private win: BrowserWindow;
  private tabs = new Map<string, TabRecord>();
  private order: string[] = [];
  private activeId: string | null = null;
  private nextId = 1;
  private persistFile: string;
  private persistTimer: NodeJS.Timeout | null = null;
  private pendingPersistJson: string | null = null;
  private persistWrite: Promise<void> = Promise.resolve();

  constructor(win: BrowserWindow) {
    this.win = win;
    this.persistFile = path.join(app.getPath('userData'), 'tabs.json');
    this.win.on('resize', () => this.layoutActive());
    this.initHealthTab();
  }

  /** Always tab[0], permanent, unclosable, never persisted -- synthesized fresh on every launch. */
  private initHealthTab(): void {
    const record: TabRecord = {
      id: 'health',
      kind: 'health',
      proxyOrigin: '',
      label: 'Health',
      view: null,
    };
    this.tabs.set(record.id, record);
    this.order.push(record.id);
    this.activeId = record.id;
  }

  // Public entry points, called from ipcMain handlers registered once in main.ts.
  switchTo(id: string): void {
    this.doSwitchTo(id);
  }

  closeTabById(id: string): void {
    this.doCloseTab(id);
  }

  openSession(sessionId: string, proxyOrigin: string): string {
    const existing = this.order.find((id) => {
      const t = this.tabs.get(id)!;
      return t.kind === 'session' && t.sessionId === sessionId;
    });
    if (existing) {
      this.doSwitchTo(existing);
      return existing;
    }
    return this.createTab('session', proxyOrigin, sessionId);
  }

  openDashboard(proxyOrigin: string): string {
    return this.createTab('dashboard', proxyOrigin);
  }

  restore(): void {
    let state: PersistedState | null = null;
    try {
      if (fs.existsSync(this.persistFile)) {
        state = JSON.parse(fs.readFileSync(this.persistFile, 'utf-8'));
      }
    } catch {
      state = null;
    }

    if (state) {
      for (const t of state.tabs) {
        this.createTab(t.kind, t.proxyOrigin, t.sessionId, false, t.currentUrl);
      }
      if (state.activeId && this.tabs.has(state.activeId)) {
        this.doSwitchTo(state.activeId);
        return;
      }
    }
    // Nothing persisted (or nothing restorable) -- still push the initial
    // tab list so the health tab shows up in the strip right away.
    this.doSwitchTo('health');
  }

  private createTab(
    kind: TabKind,
    proxyOrigin: string,
    sessionId?: string,
    activate = true,
    initialUrl?: string,
  ): string {
    const id = `tab-${this.nextId++}`;
    const view = new WebContentsView({
      webPreferences: {
        contextIsolation: true,
        sandbox: true,
      },
    });

    const record: TabRecord = {
      id,
      kind,
      sessionId,
      proxyOrigin,
      label: kind === 'dashboard' ? 'Dashboard' : 'New Session',
      view,
    };
    this.tabs.set(id, record);
    this.order.push(id);
    view.setVisible(false);
    this.win.contentView.addChildView(view);

    view.webContents.setWindowOpenHandler(({ url, disposition }) => {
      this.handleWindowOpen(record, url, disposition);
      return { action: 'deny' };
    });

    view.webContents.on('page-title-updated', (_event, title) => {
      record.label = title;
      this.pushTabList();
    });

    view.webContents.on('did-navigate', (_event, url) => {
      if (record.kind === 'dashboard') {
        record.currentUrl = url;
        this.persist();
      }
    });

    const targetUrl = initialUrl ?? urlFor(kind, proxyOrigin, sessionId);
    view.webContents.on('did-finish-load', () => {
      console.log(`[DEBUG] tab ${id} finished loading ${targetUrl}`);
    });
    view.webContents.on('did-fail-load', (_e, code, desc) => {
      console.log(`[DEBUG] tab ${id} FAILED to load ${targetUrl}: ${code} ${desc}`);
    });
    view.webContents.loadURL(targetUrl);

    if (activate) {
      this.doSwitchTo(id);
    } else {
      this.pushTabList();
    }
    this.persist();
    return id;
  }

  private handleWindowOpen(from: TabRecord, url: string, disposition: string): void {
    try {
      const target = new URL(url);
      const own = new URL(from.proxyOrigin);
      if (target.origin === own.origin) {
        const sessionId = target.searchParams.get('sessionId');
        if (sessionId) {
          this.openSession(sessionId, from.proxyOrigin);
        } else {
          this.openDashboard(from.proxyOrigin);
        }
        return;
      }
    } catch {
      // fall through to external
    }
    void disposition; // foreground vs background tab is irrelevant once we hand off externally
    void shell.openExternal(url);
  }

  private doSwitchTo(id: string): void {
    const record = this.tabs.get(id);
    if (!record) return;

    for (const tab of this.tabs.values()) {
      tab.view?.setVisible(tab.id === id);
    }
    this.activeId = id;
    if (record.view) {
      this.layoutActive();
      record.view.webContents.focus();
    } else {
      this.win.webContents.focus();
    }
    this.pushTabList();
    this.persist();
  }

  private doCloseTab(id: string): void {
    const record = this.tabs.get(id);
    if (!record || record.kind === 'health') return;

    if (this.activeId === id) {
      record.view?.setVisible(false);
      this.activeId = null;
    }
    this.tabs.delete(id);
    this.order = this.order.filter((t) => t !== id);
    if (record.view) {
      this.win.contentView.removeChildView(record.view);
      record.view.webContents.close();
    }

    if (!this.activeId && this.order.length > 0) {
      this.doSwitchTo(this.order[this.order.length - 1]);
    } else {
      this.pushTabList();
      this.persist();
    }
  }

  private layoutActive(): void {
    if (!this.activeId) return;
    const record = this.tabs.get(this.activeId);
    if (!record || !record.view) return;
    const bounds = this.win.getContentBounds();
    record.view.setBounds({
      x: 0,
      y: TAB_STRIP_HEIGHT,
      width: bounds.width,
      height: Math.max(0, bounds.height - TAB_STRIP_HEIGHT),
    });
  }

  private pushTabList(): void {
    const list: TabDescriptor[] = this.order.map((id) => {
      const t = this.tabs.get(id)!;
      return { id: t.id, kind: t.kind, label: t.label };
    });
    this.win.webContents.send('tabs:update', { tabs: list, activeId: this.activeId });
  }

  async dispose(): Promise<void> {
    await this.flushPersist();
    for (const tab of this.tabs.values()) {
      if (!tab.view) continue;
      this.win.contentView.removeChildView(tab.view);
      tab.view.webContents.close();
    }
    this.tabs.clear();
    this.order = [];
    this.activeId = null;
  }

  private persistedJson(): string {
    const data: PersistedState = {
      // The health tab is synthesized fresh on every launch, never restored.
      tabs: this.order
        .filter((id) => this.tabs.get(id)!.kind !== 'health')
        .map((id) => {
          const t = this.tabs.get(id)!;
          return {
            kind: t.kind,
            sessionId: t.sessionId,
            proxyOrigin: t.proxyOrigin,
            currentUrl: t.currentUrl,
          };
        }),
      activeId: this.activeId ?? undefined,
    };
    return JSON.stringify(data, null, 2);
  }

  private persist(): void {
    this.pendingPersistJson = this.persistedJson();
    if (this.persistTimer) {
      clearTimeout(this.persistTimer);
    }
    this.persistTimer = setTimeout(() => {
      this.persistTimer = null;
      void this.flushPersist();
    }, 100);
  }

  private async flushPersist(): Promise<void> {
    if (this.persistTimer) {
      clearTimeout(this.persistTimer);
      this.persistTimer = null;
    }

    while (this.pendingPersistJson) {
      const json = this.pendingPersistJson;
      this.pendingPersistJson = null;
      this.persistWrite = this.persistWrite
        .then(() => fsp.writeFile(this.persistFile, json))
        .catch((error) => {
          console.error(`[DEBUG] failed to persist tabs: ${String(error)}`);
        });
      await this.persistWrite;
    }
    await this.persistWrite;
  }
}
