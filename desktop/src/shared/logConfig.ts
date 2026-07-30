/**
 * Single source of truth for how many lines of the desktop server log are kept
 * in memory -- both the main process's scrollback buffer (serverLauncher.ts)
 * and the renderer's own rendered log window (renderer.ts). Deliberately a
 * plain constant with no node builtins, so it's safe to import from both the
 * main process and the Vite-bundled renderer.
 */
export const MAX_LOG_LINES = 500;
