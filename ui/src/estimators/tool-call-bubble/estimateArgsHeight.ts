// Mirrors JsonArgsViewer's JsonEntry recursion (components/JsonArgsViewer.tsx)
// to sum row heights without rendering: one row per leaf/nested key, indentation
// only shifts padding-left (no height effect), multiline leaves cap at
// JSON_VALUE_MAX_LINES lines. Does not model the "expandable" param path —
// ToolCallCard never passes a toolName to JsonArgsViewer, so that path is
// never active for the tool-call-bubble list.

import { JSON_VALUE_MAX_LINES } from "../../components/JsonArgsViewer";
import {
  JSON_FONT_SIZE_PX,
  JSON_MULTILINE_VALUE_PADDING_PX,
  JSON_ROW_MARGIN_BOTTOM_PX,
  LINE_HEIGHT_RATIO,
} from "./constants";

const oneLineRowHeight =
  JSON_FONT_SIZE_PX * LINE_HEIGHT_RATIO + JSON_ROW_MARGIN_BOTTOM_PX;

function stringifyLeaf(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value) ?? "undefined";
}

function entryHeight(value: unknown): number {
  const isNested = value !== null && typeof value === "object";
  if (isNested) {
    const children: unknown[] = Array.isArray(value)
      ? value
      : Object.values(value as Record<string, unknown>);
    return (
      oneLineRowHeight +
      children.reduce((sum: number, v) => sum + entryHeight(v), 0)
    );
  }

  const isMultiline = typeof value === "string" && value.includes("\n");
  if (!isMultiline) return oneLineRowHeight;

  const numLines = stringifyLeaf(value).split("\n").length;
  const visibleLines = Math.min(numLines, JSON_VALUE_MAX_LINES);
  return (
    visibleLines * JSON_FONT_SIZE_PX * LINE_HEIGHT_RATIO +
    JSON_MULTILINE_VALUE_PADDING_PX +
    JSON_ROW_MARGIN_BOTTOM_PX
  );
}

// args mirrors JsonArgsViewer's top-level entries (object or array); returns
// the content height only (no section padding/border — see estimateArgsSectionHeight).
export function estimateArgsContentHeight(
  args: Record<string, unknown> | unknown[],
): number {
  const values: unknown[] = Array.isArray(args) ? args : Object.values(args);
  if (values.length === 0) return 0;
  return values.reduce((sum: number, v) => sum + entryHeight(v), 0);
}
