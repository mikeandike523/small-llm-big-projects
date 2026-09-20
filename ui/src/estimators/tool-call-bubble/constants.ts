// Numeric mirrors of the CSS in css/tool-ui-css.ts, components/ToolCallCard.tsx,
// components/JsonArgsViewer.tsx and the divider/row styling in TurnContainer.tsx.
// This is an estimate feeding useVirtualizer's estimateSize, not a pixel-exact
// layout engine — TanStack's measureElement corrects the real height after
// mount. Getting within a line or two shrinks the "anchor to end" jump; it
// doesn't need to eliminate it. If the source CSS changes, update here too.

// Approximate ratio of a monospace font's rendered line height to its
// font-size under the browser default ("normal") line-height. Not set
// explicitly anywhere in our CSS, so this is an empirical constant.
export const LINE_HEIGHT_RATIO = 1.3;

// toolCallCss: border: 1px solid (top + bottom)
export const CARD_BORDER_PX = 2;

// TurnContainer's per-row wrapper style={{ paddingBottom: 12 }}, applied to
// every virtualized row (divider or card) around toolCallsVirtualizer.
export const ROW_WRAPPER_PADDING_BOTTOM_PX = 12;

// toolHeaderCss: padding: 8px 14px + font-size inherited from toolCallCss (13px)
export const HEADER_VERTICAL_PADDING_PX = 16;
export const HEADER_FONT_SIZE_PX = 13;

// toolArgsCss: padding: 8px 14px, border-top: 1px
export const ARGS_SECTION_VERTICAL_PADDING_PX = 16;
export const ARGS_SECTION_BORDER_TOP_PX = 1;

// JsonArgsViewer: jsonKeyCss/jsonValueCss font-size, jsonRowCss margin-bottom.
// jsonValueCss has 0 vertical padding; jsonValueScrollableCss has 2px top+bottom.
export const JSON_FONT_SIZE_PX = 11;
export const JSON_ROW_MARGIN_BOTTOM_PX = 2;
export const JSON_MULTILINE_VALUE_PADDING_PX = 4;

// toolResultCss/streamingResultCss/deniedToolResultCss: padding: 8px 14px
// (14px left+right — subtracted from column width for wrap math),
// border-top: 1px. streamingResultCss sets font-size: 12px explicitly;
// result/denied inherit toolCallCss's 13px.
export const RESULT_SECTION_VERTICAL_PADDING_PX = 16;
export const RESULT_SECTION_HORIZONTAL_PADDING_PX = 28;
export const RESULT_SECTION_BORDER_TOP_PX = 1;
export const RESULT_FONT_SIZE_PX = 13;
export const STREAMING_RESULT_FONT_SIZE_PX = 12;

// toolResultContainerCss: min-height: calc(10px + 28px + 10px) — reserves
// room for the absolutely-positioned expand button.
export const RESULT_CONTAINER_MIN_HEIGHT_PX = 48;

// Rewrite status spans/banners (rewriteProgressCss, rewriteFailedCss,
// rewriteSuccessBadgeCss, rewrittenArgsBannerCss): each is a single line of
// 10-11px text with ~5px padding top+bottom, plus a 1px top border on the
// first three. Close enough to treat all four as one fixed height.
export const REWRITE_BANNER_HEIGHT_PX = 21;

// originalArgsToggleCss: padding: 4px 14px, 11px font, 1px top border —
// the collapsed-by-default toggle row shown when a rewrite succeeded.
export const ORIGINAL_ARGS_TOGGLE_HEIGHT_PX = 23;

// subturnDividerCss: font-size 10px, padding 2px 0, border-top 1px, margin 2px 0.
export const DIVIDER_HEIGHT_PX = 21;
