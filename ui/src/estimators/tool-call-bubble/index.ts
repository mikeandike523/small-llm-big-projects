// Height estimator for the virtualized Tool Calls column (TurnContainer.tsx's
// toolCallsVirtualizer). Feeds useVirtualizer's estimateSize so the initial
// guess is close to the real rendered height — measureElement still corrects
// it after mount, this only shrinks the gap that causes the "anchor to end"
// scroll position to jump when a new/unmeasured row appears.
//
// Mirrors ToolCallCard.tsx's own render branching (patch rewrite states,
// truncation, streaming vs. final result) — if that component's branches
// change, this needs updating too.

import { MAX_STREAMING_CHARS } from "../../components/ToolCallCard";
import { MAX_TOOL_CHARS } from "../../constants/tool-ui-constants";
import { ToolCallEntry } from "../../types";
import { estimateArgsContentHeight } from "./estimateArgsHeight";
import { estimateResultSectionHeight } from "./estimateResultHeight";
import {
  ARGS_SECTION_BORDER_TOP_PX,
  ARGS_SECTION_VERTICAL_PADDING_PX,
  CARD_BORDER_PX,
  DIVIDER_HEIGHT_PX,
  HEADER_FONT_SIZE_PX,
  HEADER_VERTICAL_PADDING_PX,
  LINE_HEIGHT_RATIO,
  ORIGINAL_ARGS_TOGGLE_HEIGHT_PX,
  REWRITE_BANNER_HEIGHT_PX,
  RESULT_FONT_SIZE_PX,
  ROW_WRAPPER_PADDING_BOTTOM_PX,
  STREAMING_RESULT_FONT_SIZE_PX,
} from "./constants";

export function estimateDividerHeight(): number {
  return DIVIDER_HEIGHT_PX + ROW_WRAPPER_PADDING_BOTTOM_PX;
}

export function estimateToolCallCardHeight(
  tc: ToolCallEntry,
  availableWidthPx: number,
): number {
  let height =
    CARD_BORDER_PX +
    HEADER_VERTICAL_PADDING_PX +
    HEADER_FONT_SIZE_PX * LINE_HEIGHT_RATIO;

  const hasResult = tc.result !== undefined;
  const isStreaming = !hasResult && tc.streamingResult !== undefined;
  const truncated = hasResult && tc.result!.length > MAX_TOOL_CHARS;

  const rewrite = tc.patchRewrite;
  const rewriteSucceeded = rewrite?.status === "success";
  const rewriteInProgress = rewrite?.status === "in_progress";
  const rewriteFailed = rewrite?.status === "failed";

  const firstViewerArgs = rewriteSucceeded
    ? (rewrite!.originalArgs as Record<string, unknown>)
    : tc.args;

  if (Object.keys(firstViewerArgs).length > 0) {
    // Original-args section starts collapsed when a rewrite succeeded — the
    // toggle row is all that's shown until the user expands it.
    height += rewriteSucceeded
      ? ORIGINAL_ARGS_TOGGLE_HEIGHT_PX
      : ARGS_SECTION_VERTICAL_PADDING_PX +
        ARGS_SECTION_BORDER_TOP_PX +
        estimateArgsContentHeight(firstViewerArgs);
  }

  if (rewriteInProgress || rewriteFailed || rewriteSucceeded) {
    height += REWRITE_BANNER_HEIGHT_PX;
  }

  if (rewriteSucceeded && Object.keys(tc.args).length > 0) {
    height +=
      REWRITE_BANNER_HEIGHT_PX +
      ARGS_SECTION_VERTICAL_PADDING_PX +
      ARGS_SECTION_BORDER_TOP_PX +
      estimateArgsContentHeight(tc.args);
  }

  if (isStreaming && tc.streamingResult !== undefined) {
    const sr = tc.streamingResult;
    const displayResult =
      sr.length > MAX_STREAMING_CHARS
        ? `[...+${sr.length - MAX_STREAMING_CHARS} chars]\n` +
          sr.slice(-MAX_STREAMING_CHARS)
        : sr;
    height += estimateResultSectionHeight(
      displayResult,
      STREAMING_RESULT_FONT_SIZE_PX,
      availableWidthPx,
    );
  } else if (hasResult) {
    const displayResult = truncated
      ? tc.result!.slice(0, MAX_TOOL_CHARS) +
        `... (${tc.result!.length - MAX_TOOL_CHARS} more)`
      : tc.result!;
    height += estimateResultSectionHeight(
      displayResult,
      RESULT_FONT_SIZE_PX,
      availableWidthPx,
    );
  }

  return height + ROW_WRAPPER_PADDING_BOTTOM_PX;
}
