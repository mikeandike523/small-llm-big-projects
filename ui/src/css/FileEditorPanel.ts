import { css } from "@emotion/react";
import {
  fontMono,
  spAccent,
  spAccentBright,
  spBg,
  spBorder,
  spHeaderBg,
  spTabBarBg,
  spTextDim,
  spTextMain,
  spTextMuted,
} from "./SidePanelTheme";
import scrollbarCss from "./scrollBarCss";

export const editorOverlayCss = (open: boolean) => css`
  position: absolute;
  top: 0;
  bottom: 0;
  left: 100%;
  z-index: 80;
  width: clamp(440px, 54vw, 920px);
  display: ${open ? "flex" : "none"};
  flex-direction: column;
  min-width: 0;
  background: ${spBg};
  border-right: 1px solid ${spBorder};
  box-shadow: 10px 0 28px rgba(0, 0, 0, 0.46);
`;

export const editorTopBarCss = css`
  height: 35px;
  display: flex;
  flex-shrink: 0;
  min-width: 0;
  background: ${spTabBarBg};
  border-bottom: 1px solid ${spBorder};
`;

export const editorTabsCss = css`
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: stretch;
  overflow-x: auto;
  overflow-y: hidden;
  ${scrollbarCss}
`;

export const editorTabCss = (
  active: boolean,
  preview: boolean,
  dragging: boolean,
) => css`
  min-width: 96px;
  max-width: 190px;
  height: 35px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 0 7px 0 10px;
  border: 0;
  border-right: 1px solid ${spBorder};
  border-top: 1px solid ${active ? spAccentBright : "transparent"};
  background: ${active ? spBg : spHeaderBg};
  color: ${active ? spTextMain : spTextMuted};
  font-family: ${fontMono};
  font-size: 11px;
  font-style: ${preview ? "italic" : "normal"};
  cursor: ${dragging ? "grabbing" : "pointer"};
  opacity: ${dragging ? 0.55 : 1};

  &:hover {
    color: ${spTextMain};
  }
`;

export const editorTabNameCss = css`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export const dirtyMarkerCss = css`
  color: ${spAccentBright};
  font-size: 10px;
`;

export const tabCloseCss = css`
  width: 17px;
  height: 17px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 3px;
  font-style: normal;
  color: ${spTextMuted};

  &:hover {
    color: #fff;
    background: rgba(255, 255, 255, 0.12);
  }
`;

export const editorActionCss = (danger = false) => css`
  width: 36px;
  height: 35px;
  flex: 0 0 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-left: 1px solid ${spBorder};
  background: ${spTabBarBg};
  color: ${danger ? "#e06767" : spTextMuted};
  cursor: pointer;

  &:hover:not(:disabled) {
    color: ${danger ? "#ff8a8a" : spTextMain};
    background: ${danger ? "rgba(160, 45, 45, 0.2)" : spHeaderBg};
  }

  &:disabled {
    color: ${spTextDim};
    cursor: default;
  }
`;

export const editorBodyCss = css`
  flex: 1;
  min-height: 0;
  position: relative;
`;

export const editorEmptyCss = css`
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: ${spTextDim};
  font-family: ${fontMono};
  font-size: 12px;
`;

export const editorErrorCss = css`
  padding: 18px;
  color: #df8585;
  font-family: ${fontMono};
  font-size: 12px;
  white-space: pre-wrap;
`;

export const editorStatusCss = css`
  height: 23px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 0 9px;
  border-top: 1px solid ${spBorder};
  color: ${spTextMuted};
  background: ${spHeaderBg};
  font-family: ${fontMono};
  font-size: 10px;
`;

export const statusPathCss = css`
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export const statusAccentCss = css`
  color: ${spAccent};
`;
