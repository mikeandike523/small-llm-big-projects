import './downloadsApi';
import type { DesktopDownload } from '../shared/downloads';
import { pendingProgress } from '../shared/downloadDropdownSelection';
import { progressRingSvg, updateProgressRing } from '../shared/downloadStatusIcons';
import { TITLEBAR_ICONS, setButtonIcon } from './icons';

/**
 * The titlebar Downloads icon: toggles the Downloads dropdown, and while
 * anything is pending shows a ring filled to the mean progress of pending
 * downloads plus a count badge. It also tells main where the icon is, so
 * the dropdown can anchor under it.
 */
export function initDownloadsIndicator(button: HTMLButtonElement): (downloads: DesktopDownload[]) => void {
  setButtonIcon(button, TITLEBAR_ICONS.downloads);
  const ring = document.createElement('span');
  ring.className = 'downloads-indicator-ring';
  ring.setAttribute('aria-hidden', 'true');
  ring.innerHTML = progressRingSvg(0);
  const badge = document.createElement('span');
  badge.className = 'downloads-indicator-badge';
  badge.setAttribute('aria-hidden', 'true');
  button.append(ring, badge);

  button.addEventListener('click', () => void window.downloadsAPI.toggleDropdown());

  const reportAnchor = () => {
    const rect = button.getBoundingClientRect();
    window.downloadsAPI.setDropdownAnchor({ left: rect.left, right: rect.right, bottom: rect.bottom });
  };
  // The icon is right-aligned, so window resizes move it as well.
  new ResizeObserver(reportAnchor).observe(document.body);
  window.addEventListener('resize', reportAnchor);
  reportAnchor();

  return (downloads) => {
    const { count, meanPercent } = pendingProgress(downloads);
    button.classList.toggle('has-pending', count > 0);
    badge.textContent = count > 0 ? String(count) : '';
    updateProgressRing(ring, meanPercent);
    button.title = count > 0 ? `Downloads (${count} in progress)` : 'Downloads';
  };
}
