import { css } from "@emotion/react";
import {
  fontMono,
  spAccentBright,
  spBg,
  spBorder,
  spHeaderBg,
  spTextDim,
  spTextMain,
  spTextMuted,
  spTextTitle,
} from "./SidePanelTheme";
import scrollbarCss from "./scrollBarCss";
import _spin from "./_spin";

export const explorerPanelCss = css`
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  background: ${spBg};
  border-right: 1px solid ${spBorder};
`;

export const explorerHeaderCss = css`
  height: 34px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  flex-shrink: 0;
  background: ${spHeaderBg};
  border-bottom: 1px solid ${spBorder};
  color: ${spTextTitle};
  font-family: ${fontMono};
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
`;

export const explorerHeaderTitleCss = css`
  flex: 1;
  min-width: 0;
`;

export const explorerHeaderButtonCss = (active: boolean) => css`
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid ${active ? spAccentBright : "transparent"};
  border-radius: 4px;
  background: ${active ? "rgba(77, 134, 191, 0.2)" : "transparent"};
  color: ${active ? spTextMain : spTextMuted};
  cursor: pointer;

  &:hover {
    color: ${spTextMain};
    background: rgba(77, 134, 191, 0.18);
  }
`;

export const treeScrollCss = css`
  flex: 1;
  min-height: 0;
  overflow-x: auto;
  overflow-y: auto;
  padding: 6px 0 12px;
  ${scrollbarCss}
`;

export const treeCss = css`
  min-width: max-content;
  color: ${spTextMain};
  font-family: ${fontMono};
  font-size: 12px;
`;

export const nodeRowCss = (
  indent: number,
  clickable: boolean,
  focused = false,
) => css`
  width: 100%;
  min-width: max-content;
  height: 24px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px 0 ${8 + indent * 14}px;
  box-sizing: border-box;
  border: 0;
  background: ${focused ? "rgba(77, 134, 191, 0.28)" : "transparent"};
  color: ${spTextMain};
  font: inherit;
  text-align: left;
  white-space: nowrap;
  cursor: ${clickable ? "pointer" : "default"};

  &:hover {
    background: ${focused
      ? "rgba(77, 134, 191, 0.34)"
      : "rgba(77, 134, 191, 0.12)"};
  }

  &:focus-visible {
    outline: 1px solid ${spAccentBright};
    outline-offset: -1px;
  }
`;

export const chevronCss = css`
  width: 13px;
  min-width: 13px;
  display: flex;
  justify-content: center;
  color: ${spTextMuted};
`;

export const folderIconCss = css`
  width: 16px;
  min-width: 16px;
  display: flex;
  color: #c4a15a;
`;

export const fileIconCss = css`
  width: 15px;
  min-width: 15px;
  height: 17px;
`;

export const rootHomeCss = css`
  color: ${spTextDim};
`;

export const rootPathCss = css`
  color: ${spTextMain};
`;

export const statusRowCss = (indent: number, error = false) => css`
  padding: 4px 10px 4px ${41 + indent * 14}px;
  color: ${error ? "#c07268" : spTextDim};
  font-family: ${fontMono};
  font-size: 11px;
  white-space: nowrap;
`;

export const contextMenuContentCss = css`
  z-index: 200;
  min-width: 150px;
  padding: 5px;
  border: 1px solid #34465d;
  border-radius: 6px;
  background: #17202b;
  color: ${spTextMain};
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  font-family: ${fontMono};
  font-size: 12px;
`;

export const contextMenuItemCss = css`
  padding: 6px 9px;
  border-radius: 4px;
  cursor: default;
  outline: none;
  user-select: none;

  &[data-highlighted] {
    background: rgba(77, 134, 191, 0.3);
    color: #fff;
  }
`;

export const pendingDeleteCss = css`
  opacity: 0.5;
  text-decoration: line-through;
`;

export const renameInputCss = css`
  min-width: 140px;
  height: 18px;
  padding: 0 4px;
  border: 1px solid ${spAccentBright};
  border-radius: 2px;
  outline: none;
  background: #0f151d;
  color: ${spTextMain};
  font: inherit;

  &:read-only {
    opacity: 0.7;
  }
`;

export const rowStatusIconCss = (failed: boolean) => css`
  width: 14px;
  min-width: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: ${failed ? "#e06c60" : spTextMuted};
  text-decoration: none;

  ${!failed &&
  css`
    & > svg {
      animation: ${_spin} 0.7s linear infinite;
    }
  `}
`;

export const contextMenuDangerItemCss = css`
  ${contextMenuItemCss}
  color: #e06c60;

  &[data-highlighted] {
    background: rgba(204, 68, 68, 0.28);
    color: #ffb3aa;
  }
`;

export const contextMenuSeparatorCss = css`
  height: 1px;
  margin: 4px 2px;
  background: #34465d;
`;
