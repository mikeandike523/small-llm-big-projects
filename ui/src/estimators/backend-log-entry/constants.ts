// Numeric mirrors of the CSS in subcomponents/DebugPanel/BackendLogsTab.tsx,
// BackendLogEntryItem.tsx and BackendLogMultiCard.tsx. Feeds the backend-log
// virtualizer's estimateSize — measureElement corrects the real height after
// mount, this only shrinks the "anchor to end" jump on new/unmeasured rows.
// If the source CSS changes, update here too.

// logContentCss: font-size: 10px, line-height: 1.5 — both explicit in CSS,
// unlike the tool-call-bubble estimator this one needs no guessed ratio.
export const CONTENT_FONT_SIZE_PX = 10;
export const CONTENT_LINE_HEIGHT_PX = 15;

// logContentCss: padding: 1px 2px
export const CONTENT_VERTICAL_PADDING_PX = 2;
export const CONTENT_HORIZONTAL_PADDING_PX = 4;

// logLineCss: border-bottom: 1px solid — wraps single (non-multi) entries only.
export const SINGLE_ENTRY_BORDER_PX = 1;

// multiCardCss: border: 1px solid (top+bottom), padding: 4px (top+bottom,
// and separately left+right), margin: 3px 0 (top+bottom).
export const MULTI_CARD_BORDER_PX = 2;
export const MULTI_CARD_VERTICAL_PADDING_PX = 8;
export const MULTI_CARD_HORIZONTAL_PADDING_PX = 8;
export const MULTI_CARD_VERTICAL_MARGIN_PX = 6;

// logsPanelCss: padding: 6px (all sides) on the scrollable panel itself —
// reduces the width available to every row before any per-row padding.
export const PANEL_HORIZONTAL_PADDING_PX = 12;

// virtualRowCss: padding-bottom: 4px, applied to every virtualized row.
export const ROW_WRAPPER_PADDING_BOTTOM_PX = 4;
