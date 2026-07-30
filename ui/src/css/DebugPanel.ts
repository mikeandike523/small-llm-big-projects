import { css } from "@emotion/react";
import _spin from "./_spin";
import scrollbarCss from "./scrollBarCss";
import {
  fontMono,
  spAccentBright,
  spBg,
  spBorder,
  spBorderStrong,
  spBorderSubtle,
  spHeaderBg,
  spTabBarBg,
  spTextDim,
  spTextMain,
  spTextMuted,
  spTextTitle,
} from "./SidePanelTheme";

export const panelCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  flex: 1;
  background: ${spBg};
  border-right: 1px solid ${spBorder};
  overflow: hidden;
`;

export const headerCss = css`
  display: flex;
  align-items: center;
  padding: 0 10px;
  height: 34px;
  border-bottom: 1px solid ${spBorderSubtle};
  background: ${spHeaderBg};
  flex-shrink: 0;
`;

export const headerTitleCss = css`
  font-family: ${fontMono};
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: ${spTextTitle};
`;

export const tabBarCss = css`
  display: flex;
  flex-direction: row;
  height: 30px;
  border-bottom: 1px solid ${spBorderStrong};
  background: ${spTabBarBg};
  flex-shrink: 0;
  overflow: hidden;
`;

export const tabButtonCss = (active: boolean) => css`
  flex: 1;
  height: 100%;
  background: ${active ? spHeaderBg : "transparent"};
  border: none;
  border-bottom: 2px solid ${active ? spAccentBright : "transparent"};
  color: ${active ? spTextMain : spTextMuted};
  padding: 0 4px;
  font-family: ${fontMono};
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-align: center;
  cursor: pointer;
  transition:
    color 0.15s,
    background 0.15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  &:hover {
    color: ${spTextMain};
    background: ${spHeaderBg};
  }
`;

export const tabContentAreaCss = css`
  position: relative;
  flex: 1;
  overflow: hidden;
`;

export const tabPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  padding: 10px;
  ${scrollbarCss}
`;

export const promptPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  padding: 10px;
  font-family: ${fontMono};
  font-size: 10px;
  color: ${spTextMuted};
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  ${scrollbarCss}
`;

export const rowCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
`;

export const skillsCardCss = css`
  border: 1px solid ${spBorder};
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 10px;
`;

export const skillsCardHeaderCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: ${spTextTitle};
  padding: 4px 8px;
  background: ${spHeaderBg};
  border-bottom: 1px solid ${spBorder};
`;

export const skillsCardBodyCss = css`
  ${scrollbarCss}
  max-height: 100px;
  overflow-y: auto;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

export const skillsCardPathCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  color: ${spTextDim};
  word-break: break-all;
  margin-bottom: 3px;
`;

export const skillsCardFileCss = css`
  font-family: ${fontMono};
  font-size: 10px;
  color: ${spTextMuted};
`;

export const toolsCardPluginNameCss = css`
  font-family: ${fontMono};
  font-size: 10px;
  color: ${spTextTitle};
  margin-top: 3px;
`;

export const toolsCardPluginPathCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  color: ${spTextDim};
  word-break: break-all;
  margin-bottom: 2px;
`;

export const toolsCardNameCss = css`
  font-family: ${fontMono};
  font-size: 10px;
  color: ${spTextMuted};
`;

export const toolsCardDividerCss = css`
  border: none;
  border-top: 1px solid ${spBorder};
  margin: 4px 0;
`;

export const placeholderCss = css`
  font-family: ${fontMono};
  font-size: 11px;
  color: ${spTextDim};
  font-style: italic;
  padding: 4px 0;
`;

export const refreshSpinnerCss = css`
  display: inline-block;
  width: 9px;
  height: 9px;
  border: 1.5px solid rgba(111, 148, 184, 0.35);
  border-top-color: ${spTextMain};
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

export const memTabContainerCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  display: flex;
  flex-direction: column;
`;

export const memTabScrollCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  ${scrollbarCss}
`;

export const memTabFooterCss = css`
  flex-shrink: 0;
  border-top: 1px solid ${spBorderSubtle};
  padding: 0 10px;
  height: 20px;
  display: flex;
  align-items: center;
  overflow: hidden;
  background: ${spHeaderBg};
`;

export const modalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

export const modalCardCss = css`
  background: ${spHeaderBg};
  border: 1px solid ${spBorderStrong};
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  width: 600px;
  max-width: 90vw;
  max-height: 80vh;
  overflow: hidden;
`;

export const modalHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid ${spBorderSubtle};
  flex-shrink: 0;
  gap: 8px;
`;

export const modalTitleCss = css`
  font-family: ${fontMono};
  font-size: 11px;
  color: ${spTextTitle};
  word-break: break-all;
  flex: 1;
  min-width: 0;
`;

export const modalCloseButtonCss = css`
  background: transparent;
  border: none;
  color: ${spTextMuted};
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
  &:hover {
    color: ${spTextMain};
  }
`;

export const modalBodyCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  font-family: ${fontMono};
  font-size: 11px;
  color: ${spTextMain};
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  ${scrollbarCss}
`;

export const modalLoadingWrapCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px 0;
`;

export const modalSpinnerCss = css`
  width: 18px;
  height: 18px;
  border: 2px solid rgba(111, 148, 184, 0.25);
  border-top-color: ${spTextMain};
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

export const modalFooterCss = css`
  flex-shrink: 0;
  border-top: 1px solid ${spBorderSubtle};
  padding: 5px 12px;
  font-family: ${fontMono};
  font-size: 10px;
`;

export const modalFooterModifiedCss = css`
  color: #c9a05a;
  cursor: pointer;
  &:hover {
    color: #e0b878;
  }
`;

export const modalFooterDeletedCss = css`
  color: #c07268;
`;
