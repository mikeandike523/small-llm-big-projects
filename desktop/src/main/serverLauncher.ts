import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { checkServerRunning, readServerState, clearServerState, type ServerState } from './serverState';
import { LogHistory } from '../shared/logHistory';

export type HealthStatusKind = 'checking' | 'starting' | 'running' | 'unreachable' | 'failed';

export interface HealthStatus {
  kind: HealthStatusKind;
  state?: ServerState;
  detail?: string;
}

export interface ServerLifecycleCallbacks {
  onStatus: (status: HealthStatus) => void;
  onLog: (lines: string[]) => void;
}

export interface ServerLifecycleHandle {
  getSnapshot: () => { status: HealthStatus; lines: string[]; logPath: string };
  restart: () => void;
}

const HEALTH_POLL_INTERVAL_MS = 500;
const RUNNING_RECHECK_INTERVAL_MS = 5000;
const LOG_TAIL_POLL_INTERVAL_MS = 500;
// Grace period between killing the old process tree and spawning a new one,
// so the old instance's ports have a moment to actually release before the
// new `slbp server run` picks free ports.
const RESTART_RESPAWN_DELAY_MS = 800;

function logFilePath(repoRoot: string): string {
  return path.join(repoRoot, '.slbp-server.log');
}

// Mirrors find_bash() in src/utils/process.py.
const BASH_CANDIDATES = [
  'C:\\Program Files\\Git\\bin\\bash.exe',
  'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
];

function findBashExe(): string {
  for (const candidate of BASH_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return 'bash';
}

function slbpScriptPath(repoRoot: string): string {
  return path.join(repoRoot, 'slbp');
}

/**
 * Best-effort termination of whatever server process tree is currently
 * recorded in .slbp-server.json. `slbp server run` has no stop command --
 * it's designed to be Ctrl+C'd in a foreground terminal -- so for a
 * detached, backgrounded instance like the one this app spawns, a forceful
 * kill by pid is the only mechanism available.
 *
 * The recorded pid is the Python process's own (os.getpid() inside
 * server_run(), written by write_state()) -- a *child* of the bash.exe
 * process this app originally spawned, not the same pid. Killing it with
 * /T (tree) takes out Python and everything it spawned (the ui/proxy/flask
 * subprocesses); the now-parentless bash.exe wrapper has nothing left to
 * wait on and exits on its own right after.
 */
function killExistingServer(repoRoot: string): void {
  const state = readServerState(repoRoot);
  if (!state?.pid) return;
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(state.pid), '/T', '/F']);
    } else {
      process.kill(state.pid, 'SIGTERM');
    }
  } catch {
    // Best-effort -- process may already be gone.
  }
}

/**
 * Command to launch `slbp server run`, platform-specific. On Windows this
 * invokes bash.exe directly instead of going through slbp.cmd with
 * `shell: true` -- bash.exe pops its own visible console window unless
 * `windowsHide` is applied to the exact process that spawns it, and routing
 * through an extra cmd.exe hop left that unreliable.
 */
function serverCommand(repoRoot: string): { cmd: string; args: string[] } {
  if (process.platform === 'win32') {
    return { cmd: findBashExe(), args: [slbpScriptPath(repoRoot), 'server', 'run', '--desktop'] };
  }
  return { cmd: slbpScriptPath(repoRoot), args: ['server', 'run', '--desktop'] };
}

/**
 * Poll-tails a growing file from a byte offset, feeding raw text chunks into
 * `history` and notifying `onChange` whenever it changes. Polling instead of
 * fs.watch because fs.watch's behavior is inconsistent across
 * filesystems/platforms; a ~500ms lag here is invisible to a human reading a
 * log view.
 */
function tailLogFile(filePath: string, history: LogHistory, onChange: () => void): () => void {
  let offset = 0;
  try {
    offset = fs.statSync(filePath).size;
  } catch {
    offset = 0;
  }

  const poll = () => {
    let size: number;
    try {
      size = fs.statSync(filePath).size;
    } catch {
      return;
    }
    if (size < offset) {
      // The file shrank out from under us -- only possible via an external
      // truncation (desktop.slbp-process.clear-logs-on-start), since this app
      // only ever opens the log in append mode. Don't try to figure out which
      // lines are still valid -- just purge and start over as if this were a
      // fresh log, and say so immediately rather than leaving stale content
      // on screen until the next write happens to arrive.
      offset = 0;
      history.reset();
      onChange();
    }
    if (size <= offset) return;

    const fd = fs.openSync(filePath, 'r');
    try {
      const length = size - offset;
      const buf = Buffer.alloc(length);
      fs.readSync(fd, buf, 0, length, offset);
      offset = size;
      history.handleNewText(buf.toString('utf-8'));
      onChange();
    } finally {
      fs.closeSync(fd);
    }
  };

  const interval = setInterval(poll, LOG_TAIL_POLL_INTERVAL_MS);
  return () => clearInterval(interval);
}

/**
 * Locates the repo's server, starting it if needed, and keeps the caller
 * informed via onStatus/onLog for the Health tab. The server is spawned
 * detached with stdout/stderr redirected to .slbp-server.log rather than
 * piped in-memory: a detached child whose pipe-reading parent later exits
 * can block/error on write, whereas a file survives this Electron process
 * restarting, so reopening the app can resume tailing the same server.
 * Closing the app does NOT stop the server -- it's a persistent backend,
 * not something tied to a window's lifecycle.
 */
export function startServerLifecycle(
  repoRoot: string,
  callbacks: ServerLifecycleCallbacks,
): ServerLifecycleHandle {
  // Owns the rotated line history for the lifetime of this app -- persists
  // across restart() (an ordinary restart keeps scrollback from the previous
  // run), and is only ever purged by tailLogFile detecting a shrunk file.
  const logHistory = new LogHistory();
  let status: HealthStatus = { kind: 'checking' };

  // Tracks whichever tailLogFile/watchRunningForever intervals are currently
  // active, so starting a new watch cycle (adopt, respawn, or restart) can
  // tear down the previous one first. Without this, restart() would leave
  // the old cycle's intervals running alongside the new ones and every log
  // line would get reported twice.
  let stopWatchers: (() => void) | null = null;

  // Guards the kill -> respawn gap in restart() below. The renderer now keeps
  // the restart button clickable through the whole 'starting' state (not just
  // 'running'/'failed'/'unreachable'), since a hung boot -- e.g. preflight
  // checks retrying forever waiting on Docker -- never itself transitions out
  // of 'starting'. That means restart() must tolerate being invoked again
  // before its own respawn actually lands, or a double-click would kill the
  // freshly-spawned process out from under the first restart and/or spawn two
  // server processes racing for the same ports.
  let restartInFlight = false;

  const setStatus = (next: HealthStatus) => {
    status = next;
    callbacks.onStatus(next);
  };

  const notifyLogChange = () => {
    callbacks.onLog(logHistory.lines);
  };

  const watchRunningForever = (): (() => void) => {
    const interval = setInterval(async () => {
      const state = await checkServerRunning(repoRoot);
      if (!state) {
        if (status.kind !== 'unreachable') {
          setStatus({ kind: 'unreachable', detail: 'The server stopped responding.' });
        }
      } else if (status.kind !== 'running') {
        setStatus({ kind: 'running', state });
      }
    }, RUNNING_RECHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  };

  const spawnServer = () => {
    stopWatchers?.();
    stopWatchers = null;
    setStatus({ kind: 'starting' });

    const logPath = logFilePath(repoRoot);
    const fd = fs.openSync(logPath, 'a');
    const { cmd, args } = serverCommand(repoRoot);
    const child: ChildProcess = spawn(cmd, args, {
      cwd: repoRoot,
      detached: true,
      windowsHide: true,
      stdio: ['ignore', fd, fd],
    });
    fs.closeSync(fd);
    child.unref();

    const stopTail = tailLogFile(logPath, logHistory, notifyLogChange);
    stopWatchers = stopTail;

    let settled = false;
    child.once('exit', (code) => {
      if (settled) return;
      settled = true;
      const tail = logHistory.lines.slice(-10).join('\n');
      setStatus({
        kind: 'failed',
        detail:
          `slbp server run exited (code ${code ?? 'unknown'}) before becoming healthy.` +
          (tail ? `\n${tail}` : ''),
      });
    });

    // No fixed timeout here -- the subprocess's own pre-flight checks retry
    // every 10s until Docker is ready, which can legitimately take minutes
    // right after login. The child's 'exit' handler above catches real
    // failures instead.
    const poll = setInterval(async () => {
      const state = await checkServerRunning(repoRoot);
      if (state) {
        settled = true;
        clearInterval(poll);
        const stopRunningWatch = watchRunningForever();
        stopWatchers = () => {
          stopTail();
          stopRunningWatch();
        };
        setStatus({ kind: 'running', state });
      }
    }, HEALTH_POLL_INTERVAL_MS);
  };

  // Fire-and-forget: intentionally not awaited. The caller (main.ts) gets its
  // handle back immediately and creates/shows the window without waiting on
  // this at all -- the server may still be starting minutes later.
  callbacks.onStatus(status);
  void checkServerRunning(repoRoot).then((state) => {
    if (state) {
      setStatus({ kind: 'running', state });
      const stopTail = tailLogFile(logFilePath(repoRoot), logHistory, notifyLogChange);
      const stopRunningWatch = watchRunningForever();
      stopWatchers = () => {
        stopTail();
        stopRunningWatch();
      };
      return;
    }
    spawnServer();
  });

  const restart = () => {
    // Ignore re-entrant clicks (button is clickable through the entire
    // 'starting' state, and a kill+respawn cycle sits in that same state for
    // RESTART_RESPAWN_DELAY_MS) rather than kill the just-spawned process or
    // schedule a second overlapping spawnServer().
    if (restartInFlight) return;
    restartInFlight = true;

    stopWatchers?.();
    stopWatchers = null;
    // logHistory is intentionally left alone here -- an ordinary restart
    // should keep prior scrollback, same as before this refactor. Only a
    // detected file truncation (tailLogFile noticing size < offset) purges it.
    setStatus({ kind: 'starting', detail: 'Restarting server…' });
    killExistingServer(repoRoot);
    clearServerState(repoRoot);
    // spawnServer() itself is synchronous-looking but the actual OS-level
    // termination from killExistingServer needs a brief moment to fully
    // release the old instance's ports before the new one allocates fresh ones.
    setTimeout(() => {
      restartInFlight = false;
      spawnServer();
    }, RESTART_RESPAWN_DELAY_MS);
  };

  return {
    getSnapshot: () => ({ status, lines: logHistory.lines, logPath: logFilePath(repoRoot) }),
    restart,
  };
}
