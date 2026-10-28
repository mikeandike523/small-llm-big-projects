import { app, BrowserWindow, WebContentsView, shell } from 'electron';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {
  isOverlayId,
  nextActiveAfterClose,
  restoredActiveId,
  toggledOverlay,
  type OverlayId,
} from '../shared/tabSelection';

export const TAB_STRIP_HEIGHT = 40;

export type TabKind = 'session' | 'dashboard';

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
  view: WebContentsView;
}

export interface TabDescriptor {
  id: string;
  kind: TabKind;
  label: string;
}

export interface TabsUpdatePayload {
  tabs: TabDescriptor[];
  // The focus tab; null shows the base window's "No tabs open" page.
  activeId: string | null;
  // Drawn by the base window on top of the focus tab.
  overlay: OverlayId | null;
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
  activeIndex?: number;
  overlay?: OverlayId | null;
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
 *
 * Health, Settings and Downloads are not tabs but overlays (see
 * shared/tabSelection.ts): base-window pages drawn over the focus tab, whose
 * view is hidden while one is showing.
 */
export class TabManager {
  private win: BrowserWindow;
  private tabs = new Map<string, TabRecord>();
  private order: string[] = [];
  // null shows the base window's "No tabs open" page.
  private activeId: string | null = null;
  private overlay: OverlayId | null = null;
  private nextId = 1;
  private persistFile: string;
  private persistTimer: NodeJS.Timeout | null = null;
  private pendingPersistJson: string | null = null;
  private persistWrite: Promise<void> = Promise.resolve();

  constructor(
    win: BrowserWindow,
    private readonly hooks: {
      onChildViewAdded?: () => void;
      onOverlayChanged?: (overlay: OverlayId | null) => void;
    } = {},
    // Preload for session/dashboard tabs (src/tabPreload.ts).
    private readonly tabPreloadPath?: string,
  ) {
    this.win = win;
    this.persistFile = path.join(app.getPath('userData'), 'tabs.json');
    this.win.on('resize', () => this.layoutActive());
  }

  get currentOverlay(): OverlayId | null {
    return this.overlay;
  }

  /** True if `webContentsId` belongs to one of our session/dashboard tabs. */
  ownsTabWebContents(webContentsId: number): boolean {
    for (const record of this.tabs.values()) {
      if (record.view.webContents.id === webContentsId) return true;
    }
    return false;
  }

  // Public entry points, called from ipcMain handlers registered once in main.ts.
  /** Focus a tab; this also closes any overlay, since the user asked to see the tab. */
  switchTo(id: string): void {
    this.doSwitchTo(id);
  }

  toggleOverlay(id: OverlayId): void {
    this.setOverlay(toggledOverlay(this.overlay, id));
  }

  openOverlay(id: OverlayId): void {
    this.setOverlay(id);
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

    const restoredIds: string[] = [];
    for (const t of state?.tabs ?? []) {
      if (t.kind !== 'session' && t.kind !== 'dashboard') continue;
      restoredIds.push(this.createTab(t.kind, t.proxyOrigin, t.sessionId, false, t.currentUrl));
    }
    this.activeId = restoredActiveId(state?.activeIndex, restoredIds);
    // Always ends in setOverlay, which also pushes the initial tab list.
    this.setOverlay(isOverlayId(state?.overlay) ? state.overlay : null, { force: true });
  }

  private setOverlay(overlay: OverlayId | null, { force = false } = {}): void {
    if (overlay === this.overlay && !force) return;
    this.overlay = overlay;
    this.showCurrent();
    this.hooks.onOverlayChanged?.(overlay);
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
        preload: this.tabPreloadPath,
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
    this.hooks.onChildViewAdded?.();

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
    if (!this.tabs.has(id)) return;
    this.activeId = id;
    const hadOverlay = this.overlay !== null;
    this.overlay = null;
    this.showCurrent();
    if (hadOverlay) this.hooks.onOverlayChanged?.(null);
  }

  /** Show the overlay if any, else the focus tab, else the "No tabs open" page. */
  private showCurrent(): void {
    const visibleId = this.overlay ? null : this.activeId;
    for (const tab of this.tabs.values()) {
      tab.view.setVisible(tab.id === visibleId);
    }
    const visible = visibleId ? this.tabs.get(visibleId) : undefined;
    if (visible) {
      this.layoutActive();
      visible.view.webContents.focus();
    } else {
      this.win.webContents.focus();
    }
    this.pushTabList();
    this.persist();
  }

  private doCloseTab(id: string): void {
    const record = this.tabs.get(id);
    if (!record) return;

    // Chosen before removal: the right neighbour, else the left one, else the
    // "No tabs open" page. An open overlay stays open on top.
    if (this.activeId === id) this.activeId = nextActiveAfterClose(this.order, id);
    this.tabs.delete(id);
    this.order = this.order.filter((t) => t !== id);
    record.view.setVisible(false);
    this.win.contentView.removeChildView(record.view);
    record.view.webContents.close();
    this.showCurrent();
  }

  private layoutActive(): void {
    if (!this.activeId) return;
    const record = this.tabs.get(this.activeId);
    if (!record) return;
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
    const payload: TabsUpdatePayload = { tabs: list, activeId: this.activeId, overlay: this.overlay };
    this.win.webContents.send('tabs:update', payload);
  }

  async dispose(): Promise<void> {
    await this.flushPersist();
    for (const tab of this.tabs.values()) {
      this.win.contentView.removeChildView(tab.view);
      tab.view.webContents.close();
    }
    this.tabs.clear();
    this.order = [];
    this.activeId = null;
  }

  private persistedJson(): string {
    const persistedTabs: PersistedTab[] = [];
    for (const id of this.order) {
      const tab = this.tabs.get(id);
      if (!tab) continue;
      persistedTabs.push({
        kind: tab.kind,
        sessionId: tab.sessionId,
        proxyOrigin: tab.proxyOrigin,
        currentUrl: tab.currentUrl,
      });
    }
    const data: PersistedState = {
      tabs: persistedTabs,
      // Tab ids are regenerated on launch, so store the position instead.
      activeIndex: this.activeId ? this.order.indexOf(this.activeId) : undefined,
      overlay: this.overlay,
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
