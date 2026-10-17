// Height estimator for the virtualized Backend Logs list
// (BackendLogsList.tsx's virtualizer). Feeds useVirtualizer's estimateSize so
// the initial guess is close to the real rendered height — measureElement
// still corrects it after mount, this only shrinks the gap that causes the
// "anchor to end" scroll position to jump when a new/unmeasured row appears.
//
// Mirrors BackendLogEntryItem.tsx (single entries) and BackendLogMultiCard.tsx
// (grouped entries) — if those components' markup/CSS changes, this needs
// updating too.

import { BackendLogEntry } from "../../types/DebugPanel";
import { estimateContentViewHeight } from "./estimateContentHeight";
import {
  MULTI_CARD_BORDER_PX,
  MULTI_CARD_HORIZONTAL_PADDING_PX,
  MULTI_CARD_VERTICAL_MARGIN_PX,
  MULTI_CARD_VERTICAL_PADDING_PX,
  PANEL_HORIZONTAL_PADDING_PX,
  ROW_WRAPPER_PADDING_BOTTOM_PX,
  SINGLE_ENTRY_BORDER_PX,
} from "./constants";

// Per-entry cache. TanStack re-estimates every unmeasured row whenever it
// recomputes measurements -- on remount, and (with anchorTo: "end") on every
// first/last-key change, i.e. every incoming log once the buffer is full.
// Object entries cost a JSON.stringify each, so cache per entry + width.
// Evicted entries are garbage-collected out of the WeakMap.
const estimateCache = new WeakMap<
  BackendLogEntry,
  { panelWidthPx: number; height: number }
>();

export function estimateBackendLogRowHeight(
  entry: BackendLogEntry,
  panelWidthPx: number,
): number {
  const hit = estimateCache.get(entry);
  if (hit !== undefined && hit.panelWidthPx === panelWidthPx) return hit.height;

  const height = computeBackendLogRowHeight(entry, panelWidthPx);
  estimateCache.set(entry, { panelWidthPx, height });
  return height;
}

function computeBackendLogRowHeight(
  entry: BackendLogEntry,
  panelWidthPx: number,
): number {
  const rowWidthPx = Math.max(1, panelWidthPx - PANEL_HORIZONTAL_PADDING_PX);

  let height: number;
  if (entry.multiple === true) {
    const contentWidthPx = Math.max(
      1,
      rowWidthPx - MULTI_CARD_HORIZONTAL_PADDING_PX,
    );
    height =
      MULTI_CARD_BORDER_PX +
      MULTI_CARD_VERTICAL_PADDING_PX +
      MULTI_CARD_VERTICAL_MARGIN_PX +
      entry.content.reduce<number>(
        (sum, c) => sum + estimateContentViewHeight(c, contentWidthPx),
        0,
      );
  } else {
    height =
      SINGLE_ENTRY_BORDER_PX +
      estimateContentViewHeight(entry.content, rowWidthPx);
  }

  return height + ROW_WRAPPER_PADDING_BOTTOM_PX;
}
