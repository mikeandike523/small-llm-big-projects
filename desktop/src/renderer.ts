import './index.css';
import type { TabsUpdatePayload, HealthSnapshot } from './preload';
import type { HealthStatus, HealthStatusKind } from './main/serverLauncher';

declare global {
  interface Window {
    tabsAPI: {
      onUpdate: (callback: (payload: TabsUpdatePayload) => void) => void;
      switchTab: (id: string) => Promise<void>;
      closeTab: (id: string) => Promise<void>;
    };
    windowAPI: {
      minimize: () => Promise<void>;
      toggleMaximize: () => Promise<void>;
      close: () => Promise<void>;
    };
    healthAPI: {
      onStatus: (callback: (status: HealthStatus) => void) => void;
      onLogLines: (callback: (lines: string[]) => void) => void;
      getSnapshot: () => Promise<HealthSnapshot>;
      openDashboard: () => Promise<void>;
      restartServer: () => Promise<void>;
    };
  }
}

document.getElementById('win-minimize')!.addEventListener('click', () => window.windowAPI.minimize());
document.getElementById('win-maximize')!.addEventListener('click', () => window.windowAPI.toggleMaximize());
document.getElementById('win-close')!.addEventListener('click', () => window.windowAPI.close());

const stripEl = document.getElementById('tab-strip')!;
const healthPanelEl = document.getElementById('health-panel')!;
const statusBadgeEl = document.getElementById('health-status-badge')!;
const statusDetailEl = document.getElementById('health-status-detail')!;
const openDashboardBtn = document.getElementById('health-open-dashboard') as HTMLButtonElement;
const restartServerBtn = document.getElementById('health-restart-server') as HTMLButtonElement;
const logEl = document.getElementById('health-log')!;

// Mirrors serverLauncher.MAX_LOG_LINES -- kept as a local literal rather than
// a cross-process import, since the renderer bundle can't pull in the main
// process's node-only module (fs/child_process aren't available here).
const MAX_RENDERED_LOG_LINES = 5000;

function renderTabs(payload: TabsUpdatePayload) {
  stripEl.innerHTML = '';
  for (const tab of payload.tabs) {
    const tabEl = document.createElement('div');
    tabEl.className = 'tab' + (tab.id === payload.activeId ? ' tab-active' : '');

    const labelEl = document.createElement('span');
    labelEl.className = 'tab-label';
    labelEl.textContent = tab.label;
    labelEl.addEventListener('click', () => window.tabsAPI.switchTab(tab.id));
    tabEl.appendChild(labelEl);

    if (tab.kind !== 'health') {
      const closeEl = document.createElement('span');
      closeEl.className = 'tab-close';
      closeEl.textContent = '×';
      closeEl.addEventListener('click', (event) => {
        event.stopPropagation();
        window.tabsAPI.closeTab(tab.id);
      });
      tabEl.appendChild(closeEl);
    }

    stripEl.appendChild(tabEl);
  }

  healthPanelEl.classList.toggle('hidden', payload.activeId !== 'health');
}

window.tabsAPI.onUpdate(renderTabs);

// --- Health tab ---

const STATUS_LABELS: Record<HealthStatusKind, string> = {
  checking: 'Checking…',
  starting: 'Starting…',
  running: 'Running',
  unreachable: 'Unreachable',
  failed: 'Failed',
};

function renderStatus(status: HealthStatus) {
  statusBadgeEl.textContent = STATUS_LABELS[status.kind];
  statusBadgeEl.className = `health-badge health-badge-${status.kind}`;

  let detail = status.detail ?? '';
  if (status.state) {
    const portPid = `proxy port ${status.state.proxy_port}${status.state.pid ? `, pid ${status.state.pid}` : ''}`;
    detail = detail ? `${portPid} — ${detail}` : portPid;
  }
  statusDetailEl.textContent = detail;

  openDashboardBtn.disabled = status.kind !== 'running';
  // Disabled only while a (re)start is already in flight -- unlike the
  // dashboard button, this should stay clickable in 'unreachable'/'failed'
  // states, since that's exactly when a restart is most likely wanted.
  restartServerBtn.disabled = status.kind === 'checking' || status.kind === 'starting';
}

function appendLogLines(lines: string[]) {
  if (lines.length === 0) return;
  const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 4;

  const existing = logEl.textContent ? logEl.textContent.split('\n') : [];
  const combined = existing.concat(lines);
  const trimmed =
    combined.length > MAX_RENDERED_LOG_LINES
      ? combined.slice(combined.length - MAX_RENDERED_LOG_LINES)
      : combined;
  logEl.textContent = trimmed.join('\n');

  if (atBottom) {
    logEl.scrollTop = logEl.scrollHeight;
  }
}

openDashboardBtn.addEventListener('click', () => {
  void window.healthAPI.openDashboard();
});

restartServerBtn.addEventListener('click', () => {
  void window.healthAPI.restartServer();
});

window.healthAPI.onStatus(renderStatus);
window.healthAPI.onLogLines(appendLogLines);

void window.healthAPI.getSnapshot().then((snapshot) => {
  renderStatus(snapshot.status);
  if (snapshot.lines.length > 0) {
    logEl.textContent = snapshot.lines.join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  }
});
