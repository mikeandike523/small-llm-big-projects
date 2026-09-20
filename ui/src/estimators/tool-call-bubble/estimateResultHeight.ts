// Mirrors toolResultContainerCss + toolResultCss/streamingResultCss/deniedToolResultCss
// (css/tool-ui-css.ts, components/ToolCallCard.tsx): white-space pre-wrap
// wrapping simulated via countWrappedLines, floored by the container's min-height
// (which reserves room for the absolutely-positioned expand button).

import { getMonoCharWidthPx } from "../shared/monoCharMetrics";
import { countWrappedLines } from "../shared/wrapLines";
import {
  LINE_HEIGHT_RATIO,
  RESULT_CONTAINER_MIN_HEIGHT_PX,
  RESULT_SECTION_BORDER_TOP_PX,
  RESULT_SECTION_HORIZONTAL_PADDING_PX,
  RESULT_SECTION_VERTICAL_PADDING_PX,
} from "./constants";

export function estimateResultSectionHeight(
  text: string,
  fontSizePx: number,
  availableWidthPx: number,
): number {
  const textWidthPx = Math.max(
    1,
    availableWidthPx - RESULT_SECTION_HORIZONTAL_PADDING_PX,
  );
  const charWidthPx = getMonoCharWidthPx(fontSizePx);
  const lines = countWrappedLines(text, textWidthPx, charWidthPx);
  const contentHeight = lines * fontSizePx * LINE_HEIGHT_RATIO;

  const blockHeight =
    RESULT_SECTION_VERTICAL_PADDING_PX +
    RESULT_SECTION_BORDER_TOP_PX +
    contentHeight;

  return Math.max(blockHeight, RESULT_CONTAINER_MIN_HEIGHT_PX);
}
