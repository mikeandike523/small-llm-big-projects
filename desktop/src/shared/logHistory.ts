import { MAX_LOG_LINES } from './logConfig';

// Strips two kinds of bytes before they ever reach the DOM:
//  - ANSI/CSI escape sequences (e.g. "\x1b[32m ... \x1b[0m"). Not
//    hypothetical: src/cli_routes/server.py uses click.echo(termcolor.colored(...))
//    throughout with no TTY check, so it emits color codes unconditionally --
//    including when stdout is redirected to a file, which is exactly what the
//    desktop launcher does. Matching the whole sequence (not just the lone ESC
//    byte) avoids leaving trailing garbage like "32m" behind.
//  - Stray C0 control characters, DEL, and the extended Unicode "mandatory
//    line break" set (VT, FF, CR, NEL, LS, PS). Several of these -- not just
//    CR -- are treated as forced line breaks by browser text layout
//    independent of our own '\n' accounting, which is the same "unexpected
//    extra visual line" risk already identified for CR. '\t' and '\n' are
//    deliberately left out (both legitimate/expected in CLI output).
const ANSI_ESCAPE_RE = '\\x1b\\[[0-9;]*[a-zA-Z]';
const CONTROL_CHAR_CLASS = '[\\x00-\\x08\\x0B-\\x1F\\x7F\\u2028\\u2029\\u0085]';
const CONTROL_CHARS_RE = new RegExp(`${ANSI_ESCAPE_RE}|${CONTROL_CHAR_CLASS}`, 'g');

/**
 * Owns the rotated, in-memory line history for a tailed log file.
 * `lines[lines.length - 1]` is always the current line -- complete or still
 * being written -- so callers never track a separate "partial" value or
 * reconcile it with a completed-lines array at render/emit time.
 */
export class LogHistory {
  lines: string[] = [''];

  /** Purge all history, as if this were a brand new, empty log. */
  reset(): void {
    this.lines = [''];
  }

  /** Feed in a freshly-read chunk of raw log text (may or may not contain '\n'). */
  handleNewText(text: string): void {
    const clean = text.replace(CONTROL_CHARS_RE, '');
    if (!clean.includes('\n')) {
      this.lines[this.lines.length - 1] += clean;
      return;
    }
    const parts = clean.split('\n');
    this.lines[this.lines.length - 1] += parts[0];
    this.rotate();
    for (let i = 1; i < parts.length; i++) {
      this.lines.push(parts[i]);
      this.rotate();
    }
  }

  // Rotates after every single push, not once per batch, so a large burst
  // arriving in one poll can't transiently balloon memory before trimming
  // gets a chance to run.
  private rotate(): void {
    while (this.lines.length > MAX_LOG_LINES) {
      this.lines.shift();
    }
  }
}
