// Simulates white-space: pre-wrap / pre wrapping for a monospace block,
// counting visual lines from literal newlines plus width-based wraps.

export function countWrappedLines(
  text: string,
  availableWidthPx: number,
  charWidthPx: number,
): number {
  if (text.length === 0) return 1;

  const charsPerLine = Math.max(1, Math.floor(availableWidthPx / charWidthPx));
  const physicalLines = text.split("\n");

  let total = 0;
  for (const line of physicalLines) {
    total += line.length === 0 ? 1 : Math.ceil(line.length / charsPerLine);
  }
  return total;
}
