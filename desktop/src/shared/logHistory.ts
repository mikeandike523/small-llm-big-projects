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
 *
 * In addition to the visible lines, the class tracks exact *file byte*
 * positions so a later app session can prefill the widget with the same
 * lines the user last saw (see logState.ts / serverLauncher.ts). Cleaning
 * (ANSI/control stripping) changes string lengths but not the underlying
 * file's byte count, so byte accounting runs on the raw text fed in -- the
 * cleaner never removes '\n' itself, so raw and cleaned text split into the
 * same newline-delimited parts, 1:1.
 */
export class LogHistory {
  lines: string[] = [''];

  /**
   * File offset of the first byte fed into this history since the last
   * seed/reset. Callers (serverLauncher's prefill) set this so that
   * `endOffset` matches the file position just past the newest fed byte;
   * from then on every live-tail feed advances it by exactly the bytes
   * read from the file, keeping offsets exact. Zero after a plain
   * `new LogHistory()` / `reset()` (i.e. "the very start of the file").
   */
  baseOffset = 0;

  // Raw file bytes fed in since baseOffset was seeded...
  private fedBytes = 0;
  // ...and raw file bytes no longer represented by any retained line (each
  // dropped line's own bytes plus its terminating '\n').
  private droppedBytes = 0;
  // Raw file byte length per retained line, aligned 1:1 with `lines`. A
  // completed line's length includes its terminating '\n'; the trailing
  // in-progress line's does not.
  private lineBytes: number[] = [0];

  /** Purge all history, as if this were a brand new, empty log. */
  reset(): void {
    this.lines = [''];
    this.fedBytes = 0;
    this.droppedBytes = 0;
    this.lineBytes = [0];
  }

  /**
   * Feed in a freshly-read chunk of raw log text (may or may not contain
   * '\n'). `byteLength` is the chunk's byte count in the file; callers
   * reading from a Buffer pass Buffer.byteLength of the raw chunk, which
   * is not necessarily the cleaned string's length.
   */
  handleNewText(text: string, byteLength: number): void {
    const clean = text.replace(CONTROL_CHARS_RE, '');
    this.fedBytes += byteLength;
    if (!clean.includes('\n')) {
      this.lines[this.lines.length - 1] += clean;
      this.lineBytes[this.lineBytes.length - 1] += byteLength;
      return;
    }
    // rawParts and cleanParts correspond 1:1 (cleaning never touches '\n'),
    // so each part's raw byte length can be measured from the raw text.
    const rawParts = text.split('\n');
    const parts = clean.split('\n');
    this.lines[this.lines.length - 1] += parts[0];
    this.lineBytes[this.lineBytes.length - 1] += Buffer.byteLength(rawParts[0], 'utf-8');
    for (let i = 1; i < parts.length; i++) {
      // lineBytes for the line just terminated by this '\n' does not yet
      // include the newline itself; rotate() adds the +1 when dropping it.
      this.lines.push(parts[i]);
      this.lineBytes.push(Buffer.byteLength(rawParts[i], 'utf-8'));
      this.rotate();
    }
  }

  /**
   * File offset just past the newest byte fed into this history. Exact
   * provided the caller seeded `baseOffset` correctly and every
   * handleNewText call reports the true file byte count.
   */
  get endOffset(): number {
    return this.baseOffset + this.fedBytes;
  }

  /**
   * File offset of the first byte of the oldest line currently retained --
   * the value to persist so a future session can prefill this same window
   * (written to logState.json by serverLauncher when it changes).
   */
  get startOffset(): number {
    return this.baseOffset + this.droppedBytes;
  }

  // Rotates after every single push, not once per batch, so a large burst
  // arriving in one poll can't transiently balloon memory before trimming
  // gets a chance to run.
  private rotate(): void {
    while (this.lines.length > MAX_LOG_LINES) {
      this.lines.shift();
      // +1: the dropped line's terminating '\n' leaves the buffer with it.
      const droppedLineBytes = this.lineBytes.shift();
      this.droppedBytes += (droppedLineBytes ?? 0) + 1;
    }
  }
}
