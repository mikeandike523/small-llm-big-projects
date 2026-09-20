// Mirrors BackendLogContentView (subcomponents/DebugPanel/BackendLogEntryItem.tsx):
// non-object content renders as-is (untruncated); object/array content renders
// a JSON.stringify(..., null, 2) preview truncated to BACKEND_LOG_OBJECT_TRUNCATE_CHARS.
// Both paths share logContentCss, so both wrap the same way.

import { truncateForPreview } from "../../subcomponents/DebugPanel/BackendLogEntryItem";
import { BackendLogContent } from "../../types/DebugPanel";
import { getMonoCharWidthPx } from "../shared/monoCharMetrics";
import { countWrappedLines } from "../shared/wrapLines";
import {
  CONTENT_FONT_SIZE_PX,
  CONTENT_HORIZONTAL_PADDING_PX,
  CONTENT_LINE_HEIGHT_PX,
  CONTENT_VERTICAL_PADDING_PX,
} from "./constants";

function displayTextFor(content: BackendLogContent): string {
  const isObjectLike = content !== null && typeof content === "object";
  if (!isObjectLike) return String(content);
  return truncateForPreview(JSON.stringify(content, null, 2));
}

// availableWidthPx is the width of the row this content sits directly in
// (caller has already subtracted any card/panel padding around it).
export function estimateContentViewHeight(
  content: BackendLogContent,
  availableWidthPx: number,
): number {
  const text = displayTextFor(content);
  const textWidthPx = Math.max(
    1,
    availableWidthPx - CONTENT_HORIZONTAL_PADDING_PX,
  );
  const charWidthPx = getMonoCharWidthPx(CONTENT_FONT_SIZE_PX);
  const lines = countWrappedLines(text, textWidthPx, charWidthPx);

  return CONTENT_VERTICAL_PADDING_PX + lines * CONTENT_LINE_HEIGHT_PX;
}
