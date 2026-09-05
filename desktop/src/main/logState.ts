import { app } from 'electron';
import fs from 'node:fs';
import path from 'node:path';

// Per-user desktop UI state -- the same category as tabManager's tabs.json
// (userData/tabs.json), NOT cross-process coordination state like the
// repo-root .slbp-* files. It records, per tailed log file, the byte offset
// of the oldest log line the user's Health-tab widget still has in view, so
// reopening the app can prefill the widget with exactly what was last seen
// instead of starting blank. Keyed by absolute log path, so multiple repo
// checkouts (different log files) coexist cleanly inside one userData file.
interface LogStateFile {
  version: 1;
  offsets: Record<string, number>;
}

const STATE_VERSION = 1;

function stateFilePath(): string {
  return path.join(app.getPath('userData'), 'logState.json');
}

/** Returns the stored history-start offset for `logPath`, or null if absent/invalid. */
export function readLogStartOffset(logPath: string): number | null {
  try {
    const state = JSON.parse(fs.readFileSync(stateFilePath(), 'utf-8')) as LogStateFile;
    if (state.version !== STATE_VERSION) return null;
    const offset = state.offsets?.[logPath];
    return typeof offset === 'number' && Number.isFinite(offset) && offset >= 0
      ? offset
      : null;
  } catch {
    // Missing or corrupt file: caller falls back to read-last-lines.
    return null;
  }
}

/**
 * Stores the history-start offset for `logPath`. Atomic (temp file + rename)
 * so a crash mid-write can't corrupt the whole state file. Best-effort:
 * losing a write only costs the read-last-lines fallback next session.
 */
export function writeLogStartOffset(logPath: string, offset: number): void {
  let offsets: Record<string, number> = {};
  try {
    const state = JSON.parse(fs.readFileSync(stateFilePath(), 'utf-8')) as LogStateFile;
    if (state.version === STATE_VERSION) offsets = state.offsets ?? {};
  } catch {
    // Fresh file.
  }
  offsets[logPath] = offset;
  try {
    fs.mkdirSync(app.getPath('userData'), { recursive: true });
    const tmp = `${stateFilePath()}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ version: STATE_VERSION, offsets } satisfies LogStateFile, null, 2));
    fs.renameSync(tmp, stateFilePath());
  } catch {
    // Best-effort.
  }
}

/**
 * Removes the stored offset for `logPath`. Used when the log file is
 * externally truncated while being tailed: that is a "new world", so the
 * next session should fall back to read-last-lines rather than prefill from
 * an offset that no longer means anything.
 */
export function clearLogStartOffset(logPath: string): void {
  try {
    const state = JSON.parse(fs.readFileSync(stateFilePath(), 'utf-8')) as LogStateFile;
    if (state.version !== STATE_VERSION || !(logPath in (state.offsets ?? {}))) return;
    delete state.offsets[logPath];
    const tmp = `${stateFilePath()}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
    fs.renameSync(tmp, stateFilePath());
  } catch {
    // Nothing to clear / unreadable -- best-effort.
  }
}
