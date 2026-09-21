import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, '..');

function closeOnWindows() {
  const script = String.raw`
$desktopRoot = [Environment]::GetEnvironmentVariable('SLBP_DESKTOP_ROOT')
$targets = @(Get-Process -Name electron,SLBP -ErrorAction SilentlyContinue | Where-Object {
  try { $_.Path -and $_.Path.StartsWith($desktopRoot, [StringComparison]::OrdinalIgnoreCase) }
  catch { $false }
})
if ($targets.Count -eq 0) {
  Write-Host '[close-desktop] no running SLBP desktop processes found'
  exit 0
}
$pids = @($targets | ForEach-Object { [int]$_.Id })
Write-Host "[close-desktop] closing $($pids.Count) process(es): $($pids -join ', ')"
foreach ($pidValue in $pids) {
  try {
    $process = Get-Process -Id $pidValue -ErrorAction Stop
    if ($process.MainWindowHandle -ne 0) { [void]$process.CloseMainWindow() }
  } catch {}
}
$deadline = [DateTime]::UtcNow.AddSeconds(5)
do {
  Start-Sleep -Milliseconds 100
  $remaining = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
} while ($remaining.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline)
if ($remaining.Count -gt 0) {
  Write-Host "[close-desktop] force-killing remaining process(es): $($remaining -join ', ')"
  $remaining | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}
`;
  execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    stdio: 'inherit',
    env: { ...process.env, SLBP_DESKTOP_ROOT: desktopRoot },
    windowsHide: true,
  });
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function closeOnUnix() {
  const output = execFileSync('ps', ['-axo', 'pid=,command='], { encoding: 'utf8' });
  const targets = output
    .split('\n')
    .map((line) => line.trim().match(/^(\d+)\s+(.*)$/))
    .filter((match) =>
      Boolean(
        match &&
          match[2].includes(desktopRoot) &&
          (match[2].toLowerCase().includes('electron') || match[2].includes('/SLBP')),
      ),
    )
    .map((match) => Number(match[1]));
  if (targets.length === 0) {
    console.log('[close-desktop] no running SLBP desktop processes found');
    return;
  }
  console.log(`[close-desktop] terminating process(es): ${targets.join(', ')}`);
  for (const pid of targets) {
    try { process.kill(pid, 'SIGTERM'); } catch {}
  }
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline && targets.some(isAlive)) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
  }
  const remaining = targets.filter(isAlive);
  if (remaining.length > 0) {
    console.log(`[close-desktop] force-killing remaining process(es): ${remaining.join(', ')}`);
    for (const pid of remaining) {
      try { process.kill(pid, 'SIGKILL'); } catch {}
    }
  }
}

if (process.platform === 'win32') closeOnWindows();
else closeOnUnix();
