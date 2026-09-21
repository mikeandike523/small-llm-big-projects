import './index.css';
import '@xterm/xterm/css/xterm.css';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
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
    changelogAPI: {
      getVersion: () => Promise<string>;
      getIndex: () => Promise<{ releases: { version: string; date: string; file: string }[] } | null>;
      getNote: (version: string) => Promise<string | null>;
    };
    processDoctorAPI: {
      start: (cols: number, rows: number) => Promise<void>;
      write: (data: string) => void;
      resize: (cols: number, rows: number) => void;
      stop: () => Promise<void>;
      onData: (callback: (data: string) => void) => () => void;
      onExit: (callback: (exitCode: number) => void) => () => void;
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
const processDoctorBtn = document.getElementById('health-process-doctor') as HTMLButtonElement;

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

// --- Process Doctor terminal ---

const processDoctorDialog = document.getElementById('process-doctor-dialog') as HTMLDialogElement;
const processDoctorCloseBtn = document.getElementById('process-doctor-close') as HTMLButtonElement;
const processDoctorTerminalEl = document.getElementById('process-doctor-terminal')!;
let doctorTerminal: Terminal | null = null;
let doctorResizeObserver: ResizeObserver | null = null;
let removeDoctorDataListener: (() => void) | null = null;
let removeDoctorExitListener: (() => void) | null = null;

function closeProcessDoctor(): void {
  if (processDoctorDialog.open) processDoctorDialog.close();
}

function disposeProcessDoctor(): void {
  doctorResizeObserver?.disconnect();
  doctorResizeObserver = null;
  removeDoctorDataListener?.();
  removeDoctorDataListener = null;
  removeDoctorExitListener?.();
  removeDoctorExitListener = null;
  doctorTerminal?.dispose();
  doctorTerminal = null;
  processDoctorTerminalEl.replaceChildren();
  void window.processDoctorAPI.stop();
}

processDoctorBtn.addEventListener('click', () => {
  if (processDoctorDialog.open) return;
  processDoctorDialog.showModal();

  const terminal = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: "Consolas, 'Courier New', monospace",
    fontSize: 13,
    theme: { background: '#15161a', foreground: '#e8e8ec', cursor: '#e8e8ec' },
  });
  const fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(processDoctorTerminalEl);
  doctorTerminal = terminal;

  removeDoctorDataListener = window.processDoctorAPI.onData((data) => terminal.write(data));
  removeDoctorExitListener = window.processDoctorAPI.onExit((exitCode) => {
    terminal.write(`\r\n\x1b[90mProcess Doctor exited with code ${exitCode}. Close this window to continue.\x1b[0m\r\n`);
  });
  terminal.onData((data) => window.processDoctorAPI.write(data));

  const fit = () => {
    if (doctorTerminal !== terminal) return;
    try {
      fitAddon.fit();
      window.processDoctorAPI.resize(terminal.cols, terminal.rows);
    } catch {
      // The dialog can lose layout between a close event and observer delivery.
    }
  };
  doctorResizeObserver = new ResizeObserver(fit);
  doctorResizeObserver.observe(processDoctorTerminalEl);
  requestAnimationFrame(() => {
    fitAddon.fit();
    terminal.focus();
    void window.processDoctorAPI.start(terminal.cols, terminal.rows).catch((error) => {
      terminal.write(`\r\n\x1b[31mUnable to start Process Doctor: ${String(error)}\x1b[0m\r\n`);
    });
  });
});

processDoctorCloseBtn.addEventListener('click', closeProcessDoctor);
processDoctorDialog.addEventListener('click', (event) => {
  if (event.target === processDoctorDialog) closeProcessDoctor();
});
processDoctorDialog.addEventListener('close', disposeProcessDoctor);

// --- Changelog UI ---

const versionEl = document.getElementById('health-version')!;
const changelogBtn = document.getElementById('health-changelog-btn') as HTMLButtonElement;
const changelogDialog = document.getElementById('changelog-dialog') as HTMLDialogElement;
const changelogBodyEl = document.getElementById('changelog-body')!;
const changelogCloseBtn = document.getElementById('changelog-close') as HTMLButtonElement;

/**
 * Show "v1.2.3" on the health page with the latest release's message as a
 * native hover tooltip (title attribute). The version arrives first; the
 * latest note is fetched asynchronously afterwards and fills in the tooltip,
 * so the version text never blocks on disk I/O.
 */
async function loadVersion(): Promise<void> {
  const version = await window.changelogAPI.getVersion();
  if (!version) return;
  versionEl.textContent = `v${version}`;
  versionEl.title = '';
  const index = await window.changelogAPI.getIndex();
  const latest = index?.releases?.[0];
  if (latest) {
    const note = await window.changelogAPI.getNote(latest.version);
    if (note) versionEl.title = `${latest.version} (${latest.date}): ${note}`;
  }
}

changelogBtn.addEventListener('click', () => {
  changelogBodyEl.innerHTML = '';
  changelogBodyEl.textContent = 'Loading…';
  changelogDialog.showModal();
  void openChangelogDialog();
});

changelogCloseBtn.addEventListener('click', () => changelogDialog.close());
changelogDialog.addEventListener('click', (event) => {
  // Click on the backdrop (outside the dialog's content box) dismisses it.
  if (event.target === changelogDialog) changelogDialog.close();
});

async function openChangelogDialog(): Promise<void> {
  const index = await window.changelogAPI.getIndex();
  changelogBodyEl.innerHTML = '';
  if (!index || index.releases.length === 0) {
    changelogBodyEl.textContent = 'No releases recorded yet.';
    return;
  }
  // Placeholder sections first so the full list renders instantly; each
  // note's text then streams in independently as its own IPC read completes.
  for (const entry of index.releases) {
    const sectionEl = document.createElement('div');
    sectionEl.className = 'changelog-entry';

    const headEl = document.createElement('div');
    headEl.className = 'changelog-entry-head';
    const verEl = document.createElement('span');
    verEl.className = 'changelog-entry-version';
    verEl.textContent = `v${entry.version}`;
    const dateEl = document.createElement('span');
    dateEl.className = 'changelog-entry-date';
    dateEl.textContent = entry.date;
    headEl.append(verEl, dateEl);

    const noteEl = document.createElement('div');
    noteEl.className = 'changelog-entry-note';
    noteEl.textContent = '…';

    sectionEl.append(headEl, noteEl);
    changelogBodyEl.appendChild(sectionEl);

    void window.changelogAPI.getNote(entry.version).then((note) => {
      noteEl.textContent = note ?? '(no note recorded)';
    });
  }
}

void loadVersion();

window.healthAPI.onStatus(renderStatus);
window.healthAPI.onLogLines(applyLogUpdate);

void window.healthAPI.getSnapshot().then((snapshot) => {
  renderStatus(snapshot.status);
  logPathEl.textContent = snapshot.logPath;
  historyLines = snapshot.lines;
  render();
});
