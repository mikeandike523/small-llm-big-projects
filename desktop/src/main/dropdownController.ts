import { BrowserWindow, WebContentsView, type WebContents } from 'electron';
import type { DesktopDownload, DropdownAnchor, DropdownState } from '../shared/downloads';
import { addToOpenDropdown, selectDropdownIds } from '../shared/downloadDropdownSelection';
import { TAB_STRIP_HEIGHT } from './tabManager';

// The view is wider/taller than the white panel by the renderer's padding, so
// the panel's drop shadow has room to render inside the transparent view.
const DROPDOWN_WIDTH = 392;
const DROPDOWN_MARGIN = 4;
const INITIAL_HEIGHT = 120;
// Fallback in case the renderer never acknowledges its fade-out; must exceed
// DROPDOWN_FADE_MS in downloadDropdown.ts.
const CLOSE_FALLBACK_MS = 1000;

/**
 * Owns the Downloads dropdown: a transparent WebContentsView layered above the
 * tab views and anchored under the titlebar's Downloads icon.
 *
 * It opens only when a download starts (never while the Downloads page is
 * showing, which already lists it), never takes focus, and closes on a click
 * elsewhere, window blur, dismissing its last item, or the renderer's
 * auto-hide once everything in it has finished.
 *
 * Membership is a snapshot: it is chosen by selectDropdownIds() when the
 * dropdown opens and, while open, only grows (new downloads) or shrinks
 * (dismissals / history removals). Finalizing downloads update in place.
 */
export class DropdownController {
  readonly view: WebContentsView;

  // null while closed.
  private memberIds: string[] | null = null;
  private closing = false;
  private closeTimer: NodeJS.Timeout | null = null;
  private loaded = false;
  private anchor: DropdownAnchor | null = null;
  private requestedHeight = INITIAL_HEIGHT;
  // Last window-limited height sent to the renderer; -1 forces a resend.
  private sentMaxHeight = -1;

  constructor(
    private readonly win: BrowserWindow,
    private readonly allDownloads: () => DesktopDownload[],
    private readonly isSuppressed: () => boolean,
    url: string,
    preloadPath: string,
  ) {
    this.view = new WebContentsView({
      webPreferences: {
        preload: preloadPath,
        contextIsolation: true,
        sandbox: true,
        backgroundThrottling: false,
      },
    });
    this.view.setBackgroundColor('#00000000');
    this.view.setVisible(false);
    this.win.contentView.addChildView(this.view);
    this.view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    this.view.webContents.on('did-finish-load', () => {
      this.loaded = true;
      this.sentMaxHeight = -1;
      this.layout();
      this.publish();
    });
    this.view.webContents.on('render-process-gone', (_event, details) => {
      console.error(`[DEBUG] download dropdown renderer exited: ${details.reason}`);
    });
    void this.view.webContents.loadURL(url);
    this.win.on('resize', this.layout);
    this.win.on('blur', this.handleWindowBlur);
  }

  get isOpen(): boolean {
    return this.memberIds !== null;
  }

  ownsContents(contents: WebContents): boolean {
    return !this.view.webContents.isDestroyed() && this.view.webContents.id === contents.id;
  }

  bringToFront(): void {
    this.win.contentView.addChildView(this.view);
  }

  /** A download just started: add it to an open dropdown, or open one. */
  addDownload(id: string): void {
    if (this.isSuppressed()) return;
    if (this.memberIds) {
      this.memberIds = addToOpenDropdown(this.memberIds, id);
      this.publish();
      return;
    }
    this.memberIds = selectDropdownIds(this.allDownloads(), id);
    this.cancelClose();
    this.layout();
    this.publish();
    // Never takes focus from whatever the user is typing into.
    if (this.loaded) this.view.webContents.send('dropdown:opened');
  }

  removeMember(id: string): void {
    if (!this.memberIds) return;
    this.memberIds = this.memberIds.filter((memberId) => memberId !== id);
    if (this.memberIds.length === 0) this.close();
    else this.publish();
  }

  close(): void {
    if (!this.memberIds) return;
    this.memberIds = null;
    this.closing = true;
    if (this.loaded) this.view.webContents.send('dropdown:closing');
    this.closeTimer = setTimeout(() => this.finishClose(), CLOSE_FALLBACK_MS);
  }

  /** The renderer finished its fade-out. */
  finishClose(): void {
    if (!this.closing) return;
    this.cancelClose();
    this.view.setVisible(false);
  }

  setHeight(height: number): void {
    if (!Number.isFinite(height)) return;
    this.requestedHeight = Math.max(0, Math.ceil(height));
    this.layout();
  }

  setAnchor(anchor: DropdownAnchor): void {
    this.anchor = anchor;
    this.layout();
  }

  /**
   * Close on a mouse-down anywhere else, the Downloads icon included (its
   * click then opens the Downloads page). Watching input rather than focus
   * covers the dropdown never having focus, and a click into a tab view that
   * already had focus.
   */
  handleInput(contents: WebContents, input: Electron.InputEvent): void {
    if (!this.memberIds || input.type !== 'mouseDown' || this.ownsContents(contents)) return;
    this.close();
  }

  publish(): void {
    if (!this.memberIds || !this.loaded || this.view.webContents.isDestroyed()) return;
    const byId = new Map(this.allDownloads().map((download) => [download.id, download]));
    const state: DropdownState = {
      items: this.memberIds.flatMap((id) => {
        const download = byId.get(id);
        return download ? [{ ...download }] : [];
      }),
    };
    this.view.webContents.send('dropdown:update', state);
  }

  dispose(): void {
    this.cancelClose();
    this.win.off('resize', this.layout);
    this.win.off('blur', this.handleWindowBlur);
    this.win.contentView.removeChildView(this.view);
    if (!this.view.webContents.isDestroyed()) this.view.webContents.close();
  }

  private readonly handleWindowBlur = (): void => {
    this.close();
  };

  private cancelClose(): void {
    this.closing = false;
    if (this.closeTimer) {
      clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
  }

  private readonly layout = (): void => {
    const bounds = this.win.getContentBounds();
    const y = this.anchor?.bottom ?? TAB_STRIP_HEIGHT;
    const maxHeight = Math.max(0, bounds.height - y - DROPDOWN_MARGIN);
    this.sendMaxHeight(maxHeight);
    if (!this.memberIds && !this.closing) {
      this.view.setVisible(false);
      return;
    }
    const width = Math.max(0, Math.min(DROPDOWN_WIDTH, bounds.width - DROPDOWN_MARGIN * 2));
    const anchorRight = this.anchor?.right ?? bounds.width;
    const x = Math.max(DROPDOWN_MARGIN, Math.min(anchorRight - width, bounds.width - width - DROPDOWN_MARGIN));
    // Never taller than the window; the renderer's list scrolls beyond this.
    const height = Math.min(this.requestedHeight, maxHeight);
    if (width === 0 || height === 0) {
      this.view.setVisible(false);
      return;
    }
    this.view.setBounds({ x: Math.round(x), y: Math.round(y), width, height });
    this.view.setVisible(true);
  };

  /**
   * The renderer caps its list by the window's available height, not by the
   * view's current height (100vh): the view only follows the content after an
   * IPC round trip, so a 100vh cap briefly overflowed and flashed a scrollbar
   * whenever the content grew.
   */
  private sendMaxHeight(maxHeight: number): void {
    if (maxHeight === this.sentMaxHeight || !this.loaded || this.view.webContents.isDestroyed()) return;
    this.sentMaxHeight = maxHeight;
    this.view.webContents.send('dropdown:max-height', maxHeight);
  }
}
