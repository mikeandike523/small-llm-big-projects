import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';

/**
 * Desktop-app release notes, produced by release_manager.py:
 *   desktop/release-notes/changelog-index.json
 *   desktop/release-notes/<VERSION>.txt
 *
 * Resolution is exe-relative, never cwd-relative: the process cwd is
 * meaningless for a GUI app launched from a shell or file manager (it stays
 * whatever directory the shell was in). We walk up from the executable's
 * directory (and the app path as a fallback) until we find the repo root --
 * marked by a .git folder -- or hit the drive root (dirname(parent) ===
 * parent). Inability to read a directory (permission error) ends the
 * traversal rather than aborting the app. The notes then live at
 * <repoRoot>/desktop/release-notes/, which is correct for:
 *   - `pnpm start` dev runs (app path === desktop/)
 *   - `pnpm run package` run-in-place builds (exe inside desktop/out/...)
 *   - any future installed location that sits inside the repo tree
 */

export interface ChangelogIndex {
  releases: { version: string; date: string; file: string }[];
}

const REPO_MARKER = '.git';
const NOTES_DIR = 'release-notes';
const INDEX_FILE = 'changelog-index.json';

/** Walk up from `startDir` to the repo root (first ancestor containing .git). */
function findRepoRootFrom(startDir: string): string | null {
  let dir = startDir;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const marker = path.join(dir, REPO_MARKER);
    try {
      if (fs.existsSync(marker)) return dir;
    } catch {
      // A permission error on stat/read of this level ends traversal --
      // don't crash the app over release notes.
      return null;
    }
    const parent = path.dirname(dir);
    // dirname(parent) === parent means we've reached the drive/filesystem root.
    if (parent === dir) return null;
    dir = parent;
  }
}

/**
 * The notes dir is <repoRoot>/desktop/release-notes. app.getAppPath() (inside
 * the asar for packaged builds) is only a fallback for the same traversal.
 */
function resolveNotesRoot(): string | null {
  const repoRoot =
    findRepoRootFrom(path.dirname(app.getPath('exe'))) ??
    findRepoRootFrom(app.getAppPath());
  if (!repoRoot) return null;
  return path.join(repoRoot, 'desktop', NOTES_DIR);
}

export function getCurrentVersion(): string {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(app.getAppPath(), 'package.json'), 'utf-8'));
    return typeof pkg.version === 'string' ? pkg.version : '';
  } catch {
    return '';
  }
}

export function readIndex(): ChangelogIndex | null {
  const root = resolveNotesRoot();
  if (!root) return null;
  try {
    const raw = fs.readFileSync(path.join(root, INDEX_FILE), 'utf-8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.releases) ? parsed : null;
  } catch {
    return null;
  }
}

export function readNote(version: string): string | null {
  // version comes from the index we wrote ourselves; still sanitize -- the
  // renderer is untrusted input for a path join.
  if (!/^[0-9]+\.[0-9]+\.[0-9]+$/.test(version)) return null;
  const root = resolveNotesRoot();
  if (!root) return null;
  try {
    return fs.readFileSync(path.join(root, `${version}.txt`), 'utf-8').trim();
  } catch {
    return null;
  }
}
