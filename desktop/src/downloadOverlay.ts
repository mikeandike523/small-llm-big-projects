import './downloadOverlay.css';
import type { DesktopDownload } from './shared/downloads';

declare global {
  interface Window {
    downloadsAPI: {
      getSnapshot: () => Promise<DesktopDownload[]>;
      onUpdate: (callback: (downloads: DesktopDownload[]) => void) => () => void;
      setOverlayHeight: (height: number) => void;
      cancel: (id: string) => Promise<boolean>;
      dismiss: (id: string) => Promise<boolean>;
      open: (id: string) => Promise<string>;
      showInFolder: (id: string) => Promise<boolean>;
    };
  }
}

const listEl = document.getElementById('download-list')!;
let downloads: DesktopDownload[] = [];

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = -1;
  do {
    size /= 1024;
    unit += 1;
  } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

function progressDetail(download: DesktopDownload): string {
  if (download.state === 'completed') return `${formatBytes(download.receivedBytes)} · Complete`;
  if (download.state === 'cancelled') return 'Cancelled';
  if (download.state === 'failed') return download.error ?? 'Download failed';
  if (download.error) return download.error;
  const received = formatBytes(download.receivedBytes);
  const total = download.totalBytes > 0 ? ` of ${formatBytes(download.totalBytes)}` : '';
  const speed = download.bytesPerSecond > 0 ? ` · ${formatBytes(download.bytesPerSecond)}/s` : '';
  return `${received}${total}${speed}`;
}

function actionButton(label: string, action: () => Promise<unknown>): HTMLButtonElement {
  const button = document.createElement('button');
  button.className = 'download-action';
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

function downloadRow(download: DesktopDownload): HTMLElement {
  const row = document.createElement('article');
  row.className = `download-row download-${download.state}`;

  const heading = document.createElement('div');
  heading.className = 'download-heading';
  const name = document.createElement('div');
  name.className = 'download-name';
  name.textContent = download.filename;
  name.title = download.savePath;
  heading.appendChild(name);

  if (download.state !== 'progressing') {
    const dismiss = document.createElement('button');
    dismiss.className = 'download-dismiss';
    dismiss.type = 'button';
    dismiss.title = 'Dismiss';
    dismiss.setAttribute('aria-label', `Dismiss ${download.filename}`);
    dismiss.textContent = '×';
    dismiss.addEventListener('click', () => void window.downloadsAPI.dismiss(download.id));
    heading.appendChild(dismiss);
  }
  row.appendChild(heading);

  const detail = document.createElement('div');
  detail.className = 'download-detail';
  detail.textContent = progressDetail(download);
  row.appendChild(detail);

  if (download.state === 'progressing') {
    const track = document.createElement('div');
    track.className = 'download-progress-track';
    const fill = document.createElement('div');
    fill.className = 'download-progress-fill';
    if (download.totalBytes > 0) {
      const percent = Math.min(100, (download.receivedBytes / download.totalBytes) * 100);
      fill.style.width = `${percent}%`;
    } else {
      fill.classList.add('download-progress-indeterminate');
    }
    track.appendChild(fill);
    row.appendChild(track);
  }

  const actions = document.createElement('div');
  actions.className = 'download-actions';
  if (download.state === 'progressing') {
    actions.appendChild(actionButton('Cancel', () => window.downloadsAPI.cancel(download.id)));
  } else if (download.state === 'completed') {
    actions.append(
      actionButton('Open file', async () => {
        const error = await window.downloadsAPI.open(download.id);
        if (error) throw new Error(error);
      }),
      actionButton('Show in folder', () => window.downloadsAPI.showInFolder(download.id)),
    );
  }
  if (actions.childElementCount > 0) row.appendChild(actions);
  return row;
}

function render(next: DesktopDownload[]): void {
  downloads = next;
  listEl.replaceChildren(
    ...downloads
      .slice()
      .reverse()
      .map((download) => downloadRow(download)),
  );
  requestAnimationFrame(reportHeight);
}

function reportHeight(): void {
  window.downloadsAPI.setOverlayHeight(listEl.scrollHeight);
}

new ResizeObserver(reportHeight).observe(listEl);
window.downloadsAPI.onUpdate(render);
void window.downloadsAPI.getSnapshot().then(render);
