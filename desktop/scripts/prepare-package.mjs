import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(desktopRoot, '..');

function findBash() {
  if (process.platform !== 'win32') return 'bash';
  const candidates = [
    'C:\\Program Files\\Git\\bin\\bash.exe',
    'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? 'bash';
}

const doctor = spawnSync(
  findBash(),
  [path.join(repoRoot, 'slbp'), 'process-doctor', '--force-kill-all'],
  { cwd: repoRoot, stdio: 'inherit' },
);
if (doctor.error) throw doctor.error;
if (doctor.status !== 0) process.exit(doctor.status ?? 1);

const closeDesktop = spawnSync(process.execPath, [path.join(scriptDir, 'close-desktop.mjs')], {
  cwd: desktopRoot,
  stdio: 'inherit',
});
if (closeDesktop.error) throw closeDesktop.error;
process.exit(closeDesktop.status ?? 1);
