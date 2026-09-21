import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';

/**
 * Desktop-app release notes, produced by release_manager.py:
 *   desktop/desktop-release-notes/changelog-index.json
 *   desktop/desktop-release-notes/<VERSION>.txt
 *
 * Resolution is exe-relative, never cwd-relative: the process cwd is
 * meaningless for a GUI app launched from a shell or file manager (it stays
 * whatever directory the shell was in). We walk up from the executable's
 * directory (and the app path as a fallback) until we find the repo root --
 * marked by a .git folder -- or hit the drive root (dirname(parent) ===
 * parent). Inability to read a directory (permission error) ends the
 * traversal rather than aborting the app. The notes then live at
 * <repoRoot>/desktop/desktop-release-notes/, which is correct for:
 *   - `pnpm start` dev runs (app path === desktop/)
 *   - `pnpm run package` run-in-place builds (exe inside desktop/out/...)
 *   - any future installed location that sits inside the repo tree
 */

export interface ChangelogIndex {
  releases: { version: string; date: string; file: string }[];
}

const REPO_MARKER = '.git';
const NOTES_DIR = 'desktop-release-notes';
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
 * The notes dir is <repoRoot>/desktop/desktop-release-notes. app.getAppPath() (inside
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

/**
 * Compare two dotted numeric version strings ("1.10.0" vs "1.9.0").
 * Returns >0 if a is newer, <0 if b is newer, 0 if equal. Non-numeric
 * components (or malformed strings) fall back to string comparison so
 * this never throws on unexpected index content.
 */
function compareVersions(a: string, b: string): number {
  const pa = a.split('.');
  const pb = b.split('.');
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const na = Number(pa[i]);
    const nb = Number(pb[i]);
    if (Number.isFinite(na) && Number.isFinite(nb)) {
      if (na !== nb) return na - nb;
    } else {
      // Malformed component: compare the raw strings as a last resort.
      const sa = pa[i] ?? '';
      const sb = pb[i] ?? '';
      if (sa !== sb) return sa < sb ? -1 : 1;
    }
  }
  return 0;
}

/**
 * Read the changelog index and return releases sorted newest-first.
 * The index file's on-disk order is not trusted (release_manager.py may
 * append rather than prepend), so both the version tooltip and the
 * changelog dialog can rely on releases[0] being the latest version.
 */
export function readIndex(): ChangelogIndex | null {
  const root = resolveNotesRoot();
  if (!root) return null;
  try {
    const raw = fs.readFileSync(path.join(root, INDEX_FILE), 'utf-8');
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed?.releases)) return null;
    parsed.releases.sort((a: { version: string }, b: { version: string }) =>
      compareVersions(b.version, a.version),
    );
    return parsed;
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
