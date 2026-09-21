import fs from 'node:fs';
import path from 'node:path';
import * as pty from 'node-pty';

const BASH_CANDIDATES = [
  'C:\\Program Files\\Git\\bin\\bash.exe',
  'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
];

export interface ProcessDoctorCallbacks {
  onData: (data: string) => void;
  onExit: (exitCode: number) => void;
}

function findBashExe(): string {
  for (const candidate of BASH_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return 'bash';
}

function doctorCommand(repoRoot: string): { file: string; args: string[] } {
  const slbpPath = path.join(repoRoot, 'slbp');
  if (process.platform === 'win32') {
    return { file: findBashExe(), args: [slbpPath, 'process-doctor'] };
  }
  return { file: slbpPath, args: ['process-doctor'] };
}

function terminalEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) env[key] = value;
  }
  env.TERM = 'xterm-256color';
  env.COLORTERM = 'truecolor';
  return env;
}

/** Owns the single short-lived PTY shown in the Process Doctor dialog. */
export class ProcessDoctorTerminal {
  private terminal: pty.IPty | null = null;

  start(repoRoot: string, callbacks: ProcessDoctorCallbacks, cols = 100, rows = 30): void {
    this.stop();
    const { file, args } = doctorCommand(repoRoot);
    const terminal = pty.spawn(file, args, {
      name: 'xterm-256color',
      cols,
      rows,
      cwd: repoRoot,
      env: terminalEnv(),
    });
    this.terminal = terminal;
    terminal.onData(callbacks.onData);
    terminal.onExit(({ exitCode }) => {
      if (this.terminal === terminal) this.terminal = null;
      callbacks.onExit(exitCode);
    });
  }

  write(data: string): void {
    this.terminal?.write(data);
  }

  resize(cols: number, rows: number): void {
    if (!this.terminal || cols < 1 || rows < 1) return;
    this.terminal.resize(cols, rows);
  }

  stop(): void {
    const terminal = this.terminal;
    this.terminal = null;
    if (!terminal) return;
    try {
      terminal.kill();
    } catch {
      // It may have exited between the null check and kill().
    }
  }
}
