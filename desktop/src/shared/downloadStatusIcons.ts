import doneSvg from '../download-icons/done.svg?raw';
import failedSvg from '../download-icons/failed.svg?raw';
import canceledSvg from '../download-icons/canceled.svg?raw';
import type { DesktopDownload } from './downloads';
import { downloadPercent, statusKey } from './downloadFormat';

const STATUS_SVG = { done: doneSvg, failed: failedSvg, canceled: canceledSvg } as const;

/**
 * A determinate progress ring as an SVG string. pathLength="100" makes the
 * stroke-dashoffset equal to the unfilled percent, so no circumference math.
 * With `percent` null the ring spins instead (size unknown).
 */
export function progressRingSvg(percent: number | null): string {
  return `<svg class="progress-ring${percent === null ? ' progress-ring-spinning' : ''}" viewBox="0 0 24 24" aria-hidden="true">
  <circle class="progress-ring-track" cx="12" cy="12" r="10" pathLength="100" />
  <circle class="progress-ring-fill" cx="12" cy="12" r="10" pathLength="100" style="stroke-dashoffset: ${ringOffset(percent)}" />
</svg>`;
}

function ringOffset(percent: number | null): number {
  // A spinning (unknown-size) ring shows a fixed 30% arc.
  return percent === null ? 70 : 100 - Math.max(0, Math.min(100, percent));
}

/**
 * Update a ring rendered by progressRingSvg() in place, so its CSS transition
 * animates the change (re-rendering the markup would restart from scratch).
 */
export function updateProgressRing(container: Element, percent: number | null): void {
  const ring = container.querySelector<SVGSVGElement>('.progress-ring');
  const fill = container.querySelector<SVGCircleElement>('.progress-ring-fill');
  if (!ring || !fill) return;
  ring.classList.toggle('progress-ring-spinning', percent === null);
  fill.style.strokeDashoffset = String(ringOffset(percent));
}

/** Status mark for a download: a progress ring while pending, else ✓ / ✕ / ⊘. */
export function downloadStatusIcon(download: DesktopDownload): HTMLElement {
  const key = statusKey(download);
  const icon = document.createElement('span');
  icon.className = `download-status-icon download-status-${key}`;
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = key === 'pending' ? progressRingSvg(downloadPercent(download)) : STATUS_SVG[key];
  return icon;
}
