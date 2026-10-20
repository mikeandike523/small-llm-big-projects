import './titlebar/downloadsApi';
import './downloadsPage.css';
import type { DesktopDownload } from './shared/downloads';
import { downloadPercent, progressDetail, statusKey } from './shared/downloadFormat';
import { downloadStatusIcon } from './shared/downloadStatusIcons';

type StatusKey = ReturnType<typeof statusKey>;

const SECTIONS: { key: StatusKey; title: string }[] = [
  { key: 'pending', title: 'In progress' },
  { key: 'done', title: 'Completed' },
  { key: 'failed', title: 'Failed' },
  { key: 'canceled', title: 'Canceled' },
];

function newestFirst(a: DesktopDownload, b: DesktopDownload): number {
  const time = (download: DesktopDownload) =>
    download.state === 'finalized' ? download.finalizedAt : download.startedAt;
  return time(b) - time(a);
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function actionButton(label: string, action: () => Promise<unknown>, disabled = false): HTMLButtonElement {
  const button = document.createElement('button');
  button.className = 'downloads-page-action';
  button.type = 'button';
  button.textContent = label;
  button.disabled = disabled;
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

/**
 * The Downloads page: the full persisted history, grouped by status and kept
 * live. Structural changes (new entries, status changes, removals) rebuild
 * the list; progress ticks only update pending rows in place.
 */
export function initDownloadsPage(): { update: (downloads: DesktopDownload[]) => void; setVisible: (visible: boolean) => void } {
  const sectionsEl = document.getElementById('downloads-sections')!;
  const emptyEl = document.getElementById('downloads-empty')!;
  const clearBtn = document.getElementById('downloads-clear-history') as HTMLButtonElement;

  let downloads: DesktopDownload[] = [];
  let missing = new Set<string>();
  let visible = false;
  let renderedSignature: string | null = null;
  const pendingRows = new Map<string, HTMLElement>();

  clearBtn.addEventListener('click', () => {
    if (!window.confirm('Clear all finished downloads from history? Files on disk are not deleted.')) return;
    void window.downloadsAPI.clearHistory();
  });

  function buildRow(download: DesktopDownload): HTMLElement {
    const row = document.createElement('article');
    row.className = `downloads-page-row downloads-page-row-${statusKey(download)}`;
    row.appendChild(downloadStatusIcon(download));

    const body = document.createElement('div');
    body.className = 'downloads-page-row-body';
    const name = document.createElement('div');
    name.className = 'downloads-page-name';
    name.textContent = download.filename;
    const detail = document.createElement('div');
    detail.className = 'downloads-page-detail';
    const isMissing = missing.has(download.id);
    detail.textContent = isMissing ? 'File missing (moved or deleted)' : progressDetail(download);
    detail.classList.toggle('downloads-page-detail-warning', isMissing);
    const meta = document.createElement('div');
    meta.className = 'downloads-page-meta';
    meta.textContent = `${formatTime(download.startedAt)} · ${download.savePath}`;
    meta.title = download.savePath;
    body.append(name, detail, meta);

    if (download.state === 'pending') {
      const track = document.createElement('div');
      track.className = 'downloads-page-progress';
      const fill = document.createElement('div');
      fill.className = 'downloads-page-progress-fill';
      track.appendChild(fill);
      body.appendChild(track);
    }
    row.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'downloads-page-actions';
    if (download.state === 'pending') {
      actions.appendChild(actionButton('Cancel', () => window.downloadsAPI.cancel(download.id)));
    } else {
      if (download.finalizeReason === 'done') {
        actions.append(
          actionButton(
            'Open file',
            async () => {
              const error = await window.downloadsAPI.open(download.id);
              if (error) throw new Error(error);
            },
            isMissing,
          ),
          actionButton('Show in folder', () => window.downloadsAPI.showInFolder(download.id), isMissing),
        );
      }
      actions.appendChild(actionButton('Remove', () => window.downloadsAPI.removeFromHistory(download.id)));
    }
    row.appendChild(actions);
    return row;
  }

  function updatePendingRow(row: HTMLElement, download: DesktopDownload): void {
    const detail = row.querySelector('.downloads-page-detail');
    if (detail) detail.textContent = progressDetail(download);
    const fill = row.querySelector<HTMLElement>('.downloads-page-progress-fill');
    if (!fill) return;
    const percent = downloadPercent(download);
    fill.classList.toggle('indeterminate', percent === null);
    fill.style.width = percent === null ? '' : `${percent}%`;
  }

  function statusSignature(list: DesktopDownload[]): string {
    return list.map((download) => `${download.id}:${statusKey(download)}`).join(',');
  }

  function signature(): string {
    return `${statusSignature(downloads)}|${Array.from(missing).join(',')}`;
  }

  function render(): void {
    if (!visible) return;
    const nextSignature = signature();
    if (nextSignature !== renderedSignature) {
      renderedSignature = nextSignature;
      pendingRows.clear();
      const sections: HTMLElement[] = [];
      for (const { key, title } of SECTIONS) {
        const items = downloads.filter((download) => statusKey(download) === key).sort(newestFirst);
        if (items.length === 0) continue;
        const section = document.createElement('section');
        section.className = 'downloads-page-section';
        const heading = document.createElement('h2');
        heading.textContent = `${title} (${items.length})`;
        section.appendChild(heading);
        for (const download of items) {
          const row = buildRow(download);
          if (download.state === 'pending') pendingRows.set(download.id, row);
          section.appendChild(row);
        }
        sections.push(section);
      }
      sectionsEl.replaceChildren(...sections);
      emptyEl.classList.toggle('visible', downloads.length === 0);
      clearBtn.disabled = !downloads.some((download) => download.state === 'finalized');
    }
    for (const download of downloads) {
      const row = pendingRows.get(download.id);
      if (row) updatePendingRow(row, download);
    }
  }

  function refreshMissing(): void {
    void window.downloadsAPI.getMissingFileIds().then((ids) => {
      missing = new Set(ids);
      render();
    });
  }

  return {
    update(next) {
      const before = statusSignature(downloads);
      downloads = next;
      render();
      // A download just finished or was removed: recheck files on disk.
      if (visible && statusSignature(next) !== before) refreshMissing();
    },
    setVisible(nextVisible) {
      if (nextVisible === visible) return;
      visible = nextVisible;
      if (visible) {
        renderedSignature = null;
        render();
        refreshMissing();
      }
    },
  };
}
