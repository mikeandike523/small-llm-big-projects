import { css } from "@emotion/react";
import {
  spAccentBright,
  spBg,
  spBorder,
  spDividerBg,
  spDividerBgHover,
  spTextMain,
  spTextMuted,
} from "./SidePanelTheme";

const activityBarWidth = "48px";

export const sidebarCss = css`
  display: flex;
  height: 100%;
  flex-shrink: 0;
`;

export const activityBarCss = css`
  width: ${activityBarWidth};
  min-width: ${activityBarWidth};
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  background: ${spDividerBg};
  border-right: 1px solid ${spBorder};
`;

export const activityButtonCss = (active: boolean) => css`
  position: relative;
  width: ${activityBarWidth};
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-left: 2px solid ${active ? spAccentBright : "transparent"};
  background: ${active ? spDividerBgHover : "transparent"};
  color: ${active ? spTextMain : spTextMuted};
  cursor: pointer;

  svg {
    opacity: ${active ? 1 : 0.72};
    filter: ${active
      ? "drop-shadow(0 0 4px rgba(77, 134, 191, 0.45))"
      : "none"};
  }

  &:hover {
    color: ${spTextMain};
    background: ${spDividerBgHover};
  }

  &:focus-visible {
    outline: 2px solid ${spAccentBright};
    outline-offset: -2px;
  }
`;

export const panelAreaCss = css`
  position: relative;
  width: 100%;
  height: 100%;
  background: ${spBg};
`;

export const resizeHandleCss = css`
  width: 5px;
  height: 100%;
  transform: translateX(2px);
  cursor: col-resize;
  background: transparent;
  transition: background 0.1s ease;
  z-index: 20;

  &:hover,
  &:active {
    background: ${spAccentBright};
  }
`;

export const sidebarViewCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  display: flex;
  visibility: ${visible ? "visible" : "hidden"};
  pointer-events: ${visible ? "auto" : "none"};
  z-index: ${visible ? 1 : 0};
  min-width: 0;
`;
