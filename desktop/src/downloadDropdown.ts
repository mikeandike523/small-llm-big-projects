import './shared/progressRing.css';
import './downloadDropdown.css';
import type { DesktopDownload, DropdownState } from './shared/downloads';
import { downloadPercent, progressDetail, statusKey } from './shared/downloadFormat';
import { downloadStatusIcon, updateProgressRing } from './shared/downloadStatusIcons';

declare global {
  interface Window {
    dropdownAPI: {
      onUpdate: (callback: (state: DropdownState) => void) => () => void;
      onOpened: (callback: () => void) => () => void;
      onClosing: (callback: () => void) => () => void;
      onMaxHeight: (callback: (height: number) => void) => () => void;
      notifyClosed: () => void;
      setHeight: (height: number) => void;
      cancel: (id: string) => Promise<boolean>;
      dismiss: (id: string) => Promise<boolean>;
      open: (id: string) => Promise<string>;
      showInFolder: (id: string) => Promise<boolean>;
      viewAll: () => Promise<void>;
    };
  }
}

// Must cover the longest .dropdown-item transition (fade + collapse).
const LEAVE_FALLBACK_MS = 600;

const shellEl = document.getElementById('dropdown-shell')!;
const listEl = document.getElementById('dropdown-list')!;
const emptyEl = document.getElementById('dropdown-empty')!;
const viewAllBtn = document.getElementById('dropdown-view-all') as HTMLButtonElement;

interface Row {
  el: HTMLElement;
  // Status the card content was last built for; a change rebuilds it.
  status: ReturnType<typeof statusKey>;
}

const rows = new Map<string, Row>();
let shown = false;
let closing = false;

function actionButton(label: string, action: () => Promise<unknown>): HTMLButtonElement {
  const button = document.createElement('button');
  button.className = 'dropdown-action';
  button.type = 'button';
  button.textContent = label;
  button.addEventListener('click', () => {
    button.disabled = true;
    void action()
      .catch((error) => {
        button.title = String(error);
      })
      .finally(() => {
        button.disabled = false;
      });
  });
  return button;
}

function buildCard(download: DesktopDownload): HTMLElement {
  const card = document.createElement('article');
  card.className = `dropdown-card dropdown-card-${statusKey(download)}`;
  card.appendChild(downloadStatusIcon(download));

  const body = document.createElement('div');
  body.className = 'dropdown-card-body';
  const name = document.createElement('div');
  name.className = 'dropdown-card-name';
  name.textContent = download.filename;
  name.title = download.savePath;
  const detail = document.createElement('div');
  detail.className = 'dropdown-card-detail';
  detail.textContent = progressDetail(download);
  body.append(name, detail);

  const actions = document.createElement('div');
  actions.className = 'dropdown-card-actions';
  if (download.state === 'pending') {
    actions.appendChild(actionButton('Cancel', () => window.dropdownAPI.cancel(download.id)));
  } else if (download.finalizeReason === 'done') {
    actions.append(
      actionButton('Open file', async () => {
        const error = await window.dropdownAPI.open(download.id);
        if (error) throw new Error(error);
      }),
      actionButton('Show in folder', () => window.dropdownAPI.showInFolder(download.id)),
    );
  }
  if (actions.childElementCount > 0) body.appendChild(actions);
  card.appendChild(body);

  // Pending downloads can't be dismissed, only canceled.
  if (download.state === 'finalized') {
    const dismiss = document.createElement('button');
    dismiss.className = 'dropdown-dismiss';
    dismiss.type = 'button';
    dismiss.title = 'Dismiss';
    dismiss.setAttribute('aria-label', `Dismiss ${download.filename}`);
    dismiss.textContent = '×';
    dismiss.addEventListener('click', () => void window.dropdownAPI.dismiss(download.id));
    card.appendChild(dismiss);
  }
  return card;
}

/** Each row is a one-row grid so its height can animate between 0fr and 1fr. */
function createRow(download: DesktopDownload, animate: boolean): Row {
  const el = document.createElement('div');
  el.className = 'dropdown-item';
  const inner = document.createElement('div');
  inner.className = 'dropdown-item-inner';
  inner.appendChild(buildCard(download));
  el.appendChild(inner);
  if (animate) {
    el.classList.add('dropdown-item-entering');
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove('dropdown-item-entering')));
  }
  return { el, status: statusKey(download) };
}

function updateRow(row: Row, download: DesktopDownload): void {
  const status = statusKey(download);
  const inner = row.el.firstElementChild!;
  if (status !== row.status) {
    // Pending -> finalized (or similar): swap the card in place, no eviction.
    inner.replaceChildren(buildCard(download));
    row.status = status;
    return;
  }
  const detail = inner.querySelector('.dropdown-card-detail');
  if (detail) detail.textContent = progressDetail(download);
  if (status === 'pending') updateProgressRing(inner, downloadPercent(download));
}

function removeRow(id: string, row: Row, animate: boolean): void {
  rows.delete(id);
  if (!animate) {
    row.el.remove();
    return;
  }
  row.el.classList.add('dropdown-item-leaving');
  let removed = false;
  const finish = () => {
    if (removed) return;
    removed = true;
    row.el.remove();
    reportHeight();
  };
  row.el.addEventListener('transitionend', (event) => {
    if (event.target === row.el && event.propertyName === 'grid-template-rows') finish();
  });
  setTimeout(finish, LEAVE_FALLBACK_MS);
}

/** Keyed reconcile: keep DOM nodes per id so enter/leave can animate. */
function render(state: DropdownState): void {
  // Items arriving while hidden (the snapshot taken on open) just appear.
  const animate = shown;
  const nextIds = new Set(state.items.map((download) => download.id));
  for (const [id, row] of rows) {
    if (!nextIds.has(id)) removeRow(id, row, animate);
  }
  let previous: Element | null = null;
  for (const download of state.items) {
    let row = rows.get(download.id);
    if (row) {
      updateRow(row, download);
    } else {
      row = createRow(download, animate);
      rows.set(download.id, row);
    }
    // Insert in display order, skipping over rows that are still leaving.
    const expectedNext: Element | null = previous ? previous.nextElementSibling : listEl.firstElementChild;
    if (expectedNext !== row.el) listEl.insertBefore(row.el, expectedNext);
    previous = row.el;
  }
  emptyEl.classList.toggle('visible', state.items.length === 0);
  requestAnimationFrame(reportHeight);
}

/**
 * Report the panel's natural height. The list itself may be clipped by its
 * max-height (window too short), so add back its hidden scroll overflow.
 */
function reportHeight(): void {
  const natural = shellEl.offsetHeight - listEl.clientHeight + listEl.scrollHeight;
  window.dropdownAPI.setHeight(natural);
}

window.dropdownAPI.onUpdate(render);

window.dropdownAPI.onMaxHeight((height) => {
  document.documentElement.style.setProperty('--view-max-height', `${height}px`);
});

window.dropdownAPI.onOpened(() => {
  closing = false;
  requestAnimationFrame(() => {
    shown = true;
    document.body.classList.add('shown');
  });
});

window.dropdownAPI.onClosing(() => {
  closing = true;
  shown = false;
  document.body.classList.remove('shown');
});

shellEl.addEventListener('transitionend', (event) => {
  if (event.target !== shellEl || event.propertyName !== 'opacity' || !closing) return;
  closing = false;
  // Drop the stale snapshot; the next open sends a fresh one.
  for (const [id, row] of rows) removeRow(id, row, false);
  window.dropdownAPI.notifyClosed();
});

viewAllBtn.addEventListener('click', () => void window.dropdownAPI.viewAll());

new ResizeObserver(reportHeight).observe(shellEl);
