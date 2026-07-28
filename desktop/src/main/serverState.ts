import fs from 'node:fs';
import path from 'node:path';

export interface ServerState {
  proxy_port: number;
  flask_port: number;
  ui_port: number;
  pid?: number;
}

const HEALTH_TIMEOUT_MS = 1500;

export function readServerState(repoRoot: string): ServerState | null {
  const stateFile = path.join(repoRoot, '.slbp-server.json');
  try {
    if (!fs.existsSync(stateFile)) return null;
    return JSON.parse(fs.readFileSync(stateFile, 'utf-8')) as ServerState;
  } catch {
    return null;
  }
}

/** Best-effort removal of .slbp-server.json, mirroring clear_state() on the Python side. */
export function clearServerState(repoRoot: string): void {
  const stateFile = path.join(repoRoot, '.slbp-server.json');
  try {
    fs.unlinkSync(stateFile);
  } catch {
    // Already gone, or never existed -- fine either way.
  }
}

/**
 * Mirrors src/utils/server_state.py's get_running_server_state(): a present
 * .slbp-server.json only means *some* run wrote it (an unclean exit leaves
 * it behind just as often as a live server does), so presence alone isn't
 * trusted -- an existing backend route is probed through the recorded proxy
 * port to confirm the process is actually live.
 *
 * A false "not running" is far costlier than a false "running" here (it can
 * lead to spawning a duplicate server stack), so a single slow/flaky probe
 * doesn't get the final word -- retries only stop early on success.
 */
export async function checkServerRunning(
  repoRoot: string,
  retries = 2,
): Promise<ServerState | null> {
  const state = readServerState(repoRoot);
  if (!state || !state.proxy_port) return null;
  for (let i = 0; i < retries; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${state.proxy_port}/api/session-defaults`, {
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      });
      if (response.ok) return state;
    } catch {
      // not reachable this attempt
    }
  }
  return null;
}
