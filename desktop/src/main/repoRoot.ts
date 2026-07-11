import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';

/**
 * The packaged app has no fixed relative path back to the repo root (electron-forge
 * copies build output into desktop/out/, decoupled from the source tree). The CLI
 * always knows the repo root, so it passes --repo-root when spawning; walking up
 * from the app path looking for the repo's marker files is only a fallback for
 * manual (non-CLI) launches during development.
 */
function findRepoRootFrom(startDir: string): string | null {
  let dir = startDir;
  for (let i = 0; i < 8; i++) {
    if (
      fs.existsSync(path.join(dir, 'CLAUDE.md')) &&
      fs.existsSync(path.join(dir, 'desktop'))
    ) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

export function resolveRepoRoot(): string {
  const eqArg = process.argv.find((a) => a.startsWith('--repo-root='));
  if (eqArg) {
    return eqArg.slice('--repo-root='.length);
  }
  const flagIndex = process.argv.indexOf('--repo-root');
  if (flagIndex !== -1 && process.argv[flagIndex + 1]) {
    return process.argv[flagIndex + 1];
  }

  const found = findRepoRootFrom(app.getAppPath());
  if (found) return found;

  throw new Error(
    'Could not resolve the small-llm-big-projects repo root. ' +
      'Pass --repo-root <path> when launching this app (the slbp CLI does this automatically).',
  );
}
