import { BrowserWindow, WebContentsView, shell } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';

export const TAB_STRIP_HEIGHT = 40;

export type TabKind = 'session' | 'dashboard';

interface TabRecord {
  id: string;
  kind: TabKind;
  sessionId?: string;
  proxyOrigin: string;
  label: string;
  view: WebContentsView;
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
 * Only the active tab's view is attached at any time (switching detaches/
 * reattaches rather than destroying, so backgrounded tabs keep their socket
 * connections alive). Tabs are persisted to disk so a relaunch can restore them.
 */
export class TabManager {
  private win: BrowserWindow;
  private tabs = new Map<string, TabRecord>();
  private order: string[] = [];
  private activeId: string | null = null;
  private nextId = 1;
  private persistFile: string;

  constructor(win: BrowserWindow) {
    this.win = win;
    this.persistFile = path.join(app.getPath('userData'), 'tabs.json');
    this.win.on('resize', () => this.layoutActive());
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
    const existing = this.order.find((id) => this.tabs.get(id)!.kind === 'dashboard');
    if (existing) {
      this.doSwitchTo(existing);
      return existing;
    }
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

    if (!state || state.tabs.length === 0) {
      return;
    }
    for (const t of state.tabs) {
      this.createTab(t.kind, t.proxyOrigin, t.sessionId);
    }
    if (state.activeId && this.tabs.has(state.activeId)) {
      this.doSwitchTo(state.activeId);
    }
  }

  private createTab(kind: TabKind, proxyOrigin: string, sessionId?: string): string {
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

    view.webContents.setWindowOpenHandler(({ url, disposition }) => {
      this.handleWindowOpen(record, url, disposition);
      return { action: 'deny' };
    });

    view.webContents.on('page-title-updated', (_event, title) => {
      record.label = title;
      this.pushTabList();
    });

    const targetUrl = urlFor(kind, proxyOrigin, sessionId);
    view.webContents.on('did-finish-load', () => {
      console.log(`[DEBUG] tab ${id} finished loading ${targetUrl}`);
    });
    view.webContents.on('did-fail-load', (_e, code, desc) => {
      console.log(`[DEBUG] tab ${id} FAILED to load ${targetUrl}: ${code} ${desc}`);
    });
    view.webContents.loadURL(targetUrl);

    this.doSwitchTo(id);
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

    if (this.activeId && this.activeId !== id) {
      const prev = this.tabs.get(this.activeId);
      if (prev) this.win.contentView.removeChildView(prev.view);
    }
    this.activeId = id;
    this.win.contentView.addChildView(record.view);
    this.layoutActive();
    this.pushTabList();
    this.persist();
  }

  private doCloseTab(id: string): void {
    const record = this.tabs.get(id);
    if (!record) return;

    if (this.activeId === id) {
      this.win.contentView.removeChildView(record.view);
      this.activeId = null;
    }
    this.tabs.delete(id);
    this.order = this.order.filter((t) => t !== id);
    record.view.webContents.close();

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
    this.win.webContents.send('tabs:update', { tabs: list, activeId: this.activeId });
  }

  private persist(): void {
    const data: PersistedState = {
      tabs: this.order.map((id) => {
        const t = this.tabs.get(id)!;
        return { kind: t.kind, sessionId: t.sessionId, proxyOrigin: t.proxyOrigin };
      }),
      activeId: this.activeId ?? undefined,
    };
    fs.writeFileSync(this.persistFile, JSON.stringify(data, null, 2));
  }
}
