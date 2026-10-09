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

export const nodeRowCss = (indent: number, clickable: boolean) => css`
  width: 100%;
  min-width: max-content;
  height: 24px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px 0 ${8 + indent * 14}px;
  box-sizing: border-box;
  border: 0;
  background: transparent;
  color: ${spTextMain};
  font: inherit;
  text-align: left;
  white-space: nowrap;
  cursor: ${clickable ? "pointer" : "default"};

  &:hover {
    background: rgba(77, 134, 191, 0.12);
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
