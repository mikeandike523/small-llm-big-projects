// Synchronous monospace character-width calibration via canvas measureText.
// Avoids assuming Consolas metrics directly — if the browser substitutes a
// fallback monospace font (e.g. no Consolas on the host OS), this measures
// whatever font actually resolves for the given CSS font string.

const FONT_FAMILY = `"Consolas", monospace`;

let ctx: CanvasRenderingContext2D | null = null;
const cache = new Map<number, number>();

function getContext(): CanvasRenderingContext2D | null {
  if (ctx) return ctx;
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  ctx = canvas.getContext("2d");
  return ctx;
}

// Returns the pixel width of one monospace character at the given font size.
// Falls back to a 0.6x-of-font-size estimate when canvas is unavailable
// (e.g. SSR/test environments).
export function getMonoCharWidthPx(fontSizePx: number): number {
  const cached = cache.get(fontSizePx);
  if (cached !== undefined) return cached;

  const context = getContext();
  let width: number;
  if (context) {
    context.font = `${fontSizePx}px ${FONT_FAMILY}`;
    width = context.measureText("0").width;
  } else {
    width = fontSizePx * 0.6;
  }

  cache.set(fontSizePx, width);
  return width;
}
