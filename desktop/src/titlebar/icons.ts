import healthSvg from '../titlebar-icons/health.svg?raw';
import settingsSvg from '../titlebar-icons/settings.svg?raw';
import downloadsSvg from '../titlebar-icons/downloads.svg?raw';
import newDashboardSvg from '../titlebar-icons/new-dashboard.svg?raw';

export const TITLEBAR_ICONS = {
  health: healthSvg,
  settings: settingsSvg,
  downloads: downloadsSvg,
  newDashboard: newDashboardSvg,
} as const;

/** Inline an icon into a button (inline so it inherits the button's CSS color). */
export function setButtonIcon(button: HTMLElement, svg: string): void {
  const glyph = document.createElement('span');
  glyph.className = 'titlebar-icon-glyph';
  glyph.setAttribute('aria-hidden', 'true');
  glyph.innerHTML = svg;
  button.replaceChildren(glyph);
}
