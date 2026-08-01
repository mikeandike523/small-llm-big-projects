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
const tabDashboardBtn = document.getElementById('tab-dashboard-btn') as HTMLButtonElement;
const logEl = document.getElementById('health-log')!;
const logPathEl = document.getElementById('health-log-path')!;
const copyLogPathBtn = document.getElementById('health-copy-log-path') as HTMLButtonElement;

// Whether the log view should auto-follow new lines. Tracked via a live scroll
// listener rather than recomputed from logEl.scrollTop/scrollHeight at append time --
// those read as 0 while the Health tab isn't the active tab (display:none collapses
// layout), which would otherwise make "am I at the bottom?" always true while hidden
// and then desync once the tab (with real, tall content) is shown again.
let stickToBottom = true;
logEl.addEventListener('scroll', () => {
  stickToBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 4;
});

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

  const wasHidden = healthPanelEl.classList.contains('hidden');
  const isHealthActive = payload.activeId === 'health';
  healthPanelEl.classList.toggle('hidden', !isHealthActive);

  if (isHealthActive && wasHidden) {
    // While hidden the panel is display:none, so #health-log's scrollTop/scrollHeight
    // read as 0 the whole time -- any "stick to bottom" bookkeeping done during that
    // window is meaningless. Resync to the bottom now that real layout exists, rather
    // than leaving scrollTop stranded at 0 against the now-tall content.
    stickToBottom = true;
    logEl.scrollTop = logEl.scrollHeight;
  }
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
  // Disabled only during the brief initial 'checking' probe (nothing to kill
  // or restart yet). Deliberately stays clickable through 'starting' too --
  // unlike the dashboard button -- since a hung boot (e.g. preflight checks
  // retrying forever waiting on Docker) never leaves 'starting' on its own,
  // and that's exactly when a force-kill-and-restart is most needed. The
  // main-process restart() call is re-entrancy-guarded (see
  // `restartInFlight` in serverLauncher.ts) so repeated clicks here can't
  // race a kill against a not-yet-finished respawn.
  restartServerBtn.disabled = status.kind === 'checking';
  tabDashboardBtn.disabled = status.kind !== 'running';
}

// The renderer holds no line-history logic of its own -- the main process's
// LogHistory (shared/logHistory.ts) is the sole source of truth, rotation
// included. This is purely a mirror of whatever array it was last handed.
let historyLines: string[] = [];

function render() {
  logEl.textContent = historyLines.join('\n');
  if (stickToBottom) {
    logEl.scrollTop = logEl.scrollHeight;
  }
}

function applyLogUpdate(lines: string[]) {
  historyLines = lines;
  render();
}

copyLogPathBtn.addEventListener('click', () => {
  const path = logPathEl.textContent;
  if (!path) return;
  void navigator.clipboard.writeText(path).then(() => {
    const original = copyLogPathBtn.textContent;
    copyLogPathBtn.textContent = '✓';
    setTimeout(() => {
      copyLogPathBtn.textContent = original;
    }, 1200);
  });
});

openDashboardBtn.addEventListener('click', () => {
  void window.healthAPI.openDashboard();
});

tabDashboardBtn.addEventListener('click', () => {
  void window.healthAPI.openDashboard();
});

restartServerBtn.addEventListener('click', () => {
  void window.healthAPI.restartServer();
});

window.healthAPI.onStatus(renderStatus);
window.healthAPI.onLogLines(applyLogUpdate);

void window.healthAPI.getSnapshot().then((snapshot) => {
  renderStatus(snapshot.status);
  logPathEl.textContent = snapshot.logPath;
  historyLines = snapshot.lines;
  render();
});
