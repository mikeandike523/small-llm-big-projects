// Height estimator for the virtualized Backend Logs list
// (BackendLogsTab.tsx's virtualizer). Feeds useVirtualizer's estimateSize so
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

export function estimateBackendLogRowHeight(
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
