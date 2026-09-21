import { css } from "@emotion/react";

/** Height of the bottom-edge glow bar in the tool-calls virtual list.
 *  Kept narrower than the backend-logs variant because the darker
 *  background provides more contrast. */
export const SHINE_HEIGHT_TOOL_CALLS_PX = 10;

/** Height of the bottom-edge glow bar in the backend-logs virtual list.
 *  Wider than the tool-calls variant for visibility against lighter content. */
export const SHINE_HEIGHT_BACKEND_LOGS_PX = 16;

/** Shared auto-scroll shine: a purple gradient pinned to the bottom of a
 *  containing block (position: relative required on the parent). Fades in/out
 *  via opacity transition driven by the `active` boolean. */
export function autoScrollShineCss(active: boolean, heightPx: number) {
  return css`
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: ${heightPx}px;
    pointer-events: none;
    opacity: ${active ? 1 : 0};
    transition: opacity 220ms ease;
    background: linear-gradient(
      to top,
      rgba(160, 110, 230, 0.55),
      rgba(160, 110, 230, 0)
    );
  `;
}
