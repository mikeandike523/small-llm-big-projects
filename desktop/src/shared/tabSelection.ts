/**
 * The window shows one focus tab (a session/dashboard tab, or the "No tabs
 * open" page when there is none) with at most one full-size overlay page on
 * top. Each overlay's titlebar icon toggles it; the focus tab underneath is
 * untouched by opening or closing an overlay.
 */
export const OVERLAY_IDS = ['health', 'settings', 'downloads'] as const;
export type OverlayId = (typeof OVERLAY_IDS)[number];

export function isOverlayId(value: unknown): value is OverlayId {
  return OVERLAY_IDS.includes(value as OverlayId);
}

/** Clicking an overlay's icon closes it if it is showing, else shows it. */
export function toggledOverlay(current: OverlayId | null, clicked: OverlayId): OverlayId | null {
  return current === clicked ? null : clicked;
}

/**
 * Which tab becomes the focus tab after the focus tab closes: its right
 * neighbour, else its left neighbour, else null (the "No tabs open" page).
 */
export function nextActiveAfterClose(tabIds: readonly string[], closedId: string): string | null {
  const index = tabIds.indexOf(closedId);
  if (index === -1) return null;
  return tabIds[index + 1] ?? tabIds[index - 1] ?? null;
}

/**
 * Tab ids are regenerated on every launch, so the focus tab is persisted by
 * position; an out-of-range position falls back to the first tab.
 */
export function restoredActiveId(activeIndex: unknown, restoredIds: readonly string[]): string | null {
  const index = typeof activeIndex === 'number' ? activeIndex : 0;
  return restoredIds[index] ?? restoredIds[0] ?? null;
}
