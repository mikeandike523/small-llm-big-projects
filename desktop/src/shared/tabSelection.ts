/**
 * Which strip tab becomes active after the active one closes: its right
 * neighbour, else its left neighbour, else null (the "No tabs open" page).
 * Built-in pages (Health, Settings, Downloads) are never picked implicitly.
 */
export function nextActiveAfterClose(stripIds: readonly string[], closedId: string): string | null {
  const index = stripIds.indexOf(closedId);
  if (index === -1) return null;
  return stripIds[index + 1] ?? stripIds[index - 1] ?? null;
}

/**
 * Persisted pointer to the active tab. Strip tab ids are regenerated on every
 * launch, so they are stored by position; built-in ids are stable.
 */
export type PersistedActive = { stripIndex: number } | { builtInId: string } | null;

export function restoredActiveId(
  active: PersistedActive | undefined,
  restoredStripIds: readonly string[],
  builtInIds: readonly string[],
): string | null {
  if (active && 'builtInId' in active && builtInIds.includes(active.builtInId)) return active.builtInId;
  if (active && 'stripIndex' in active) {
    const id = restoredStripIds[active.stripIndex];
    if (id) return id;
  }
  return restoredStripIds[0] ?? null;
}
