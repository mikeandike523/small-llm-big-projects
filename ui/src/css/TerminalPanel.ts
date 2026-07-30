import { css, keyframes } from "@emotion/react";
import {
  fontMono,
  spAccent,
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
  border-left: 1px solid ${spBorder};
  overflow: hidden;
  position: relative;
`;

export const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 34px;
  padding: 0 10px;
  background: ${spHeaderBg};
  border-bottom: 1px solid ${spBorderSubtle};
  flex-shrink: 0;
`;

export const titleCss = css`
  font-family: ${fontMono};
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: ${spTextTitle};
`;

export const tabBarCss = css`
  display: flex;
  align-items: flex-end;
  gap: 4px;
  min-height: 36px;
  padding: 5px 8px 0 8px;
  border-bottom: 1px solid ${spBorderStrong};
  background: ${spTabBarBg};
  overflow-x: auto;
  flex-shrink: 0;
`;

export const tabButtonCss = (active: boolean, exited: boolean) => css`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 160px;
  min-width: 0;
  height: 26px;
  padding: 0 8px;
  border-radius: 4px 4px 0 0;
  border: 1px solid ${active ? spAccent : spBorder};
  border-bottom-color: ${active ? spBg : spBorderStrong};
  background: ${active ? spBg : spHeaderBg};
  color: ${exited ? spTextDim : active ? spTextMain : spTextMuted};
  font-family: ${fontMono};
  font-size: 11px;
  cursor: pointer;
  margin-bottom: -1px;
  position: relative;
  z-index: ${active ? 1 : 0};
  &:hover {
    border-color: ${spAccentBright};
    border-bottom-color: ${active ? spBg : spBorderStrong};
    color: ${exited ? spTextDim : spTextMain};
  }
`;

export const tabNameCss = css`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export const closeTabCss = css`
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 0;
  opacity: 0.7;
  &:hover {
    opacity: 1;
  }
`;

export const newButtonCss = css`
  height: 24px;
  padding: 0 10px;
  border-radius: 5px;
  border: 1px solid ${spBorder};
  background: ${spHeaderBg};
  color: ${spTextMuted};
  font-family: ${fontMono};
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  &:hover {
    background: ${spTabBarBg};
    border-color: ${spAccentBright};
    color: ${spTextMain};
  }
`;

export const terminalsCss = css`
  position: relative;
  flex: 1;
  min-height: 0;
  background: #0d0d0d;
`;

export const terminalContainerCss = (active: boolean) => css`
  position: absolute;
  inset: 0;
  display: ${active ? "block" : "none"};
  padding: 8px;
  box-sizing: border-box;
  overflow: hidden;
  .xterm {
    height: 100%;
  }
`;

export const emptyCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 0;
  color: ${spTextDim};
  font-family: ${fontMono};
  font-size: 12px;
`;

export const tooltipFadeIn = keyframes`
  from { opacity: 0; }
  to   { opacity: 1; }
`;

export const tooltipFadeOut = keyframes`
  from { opacity: 1; }
  to   { opacity: 0; }
`;

export const tooltipCss = (visible: boolean) => css`
  position: fixed;
  transform: translate(-50%, calc(-100% - 6px));
  background: ${spHeaderBg};
  border: 1px solid ${spBorderStrong};
  border-radius: 4px;
  color: ${spTextMain};
  font-family: ${fontMono};
  font-size: 10px;
  padding: 3px 8px;
  white-space: nowrap;
  pointer-events: none;
  z-index: 9999;
  animation: ${visible ? tooltipFadeIn : tooltipFadeOut} 80ms ease forwards;
`;

export const footerCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  padding: 0 12px;
  background: ${spHeaderBg};
  border-top: 1px solid ${spBorderSubtle};
  flex-shrink: 0;
`;

export const askButtonCss = css`
  height: 30px;
  padding: 0 18px;
  border-radius: 6px;
  border: 1px solid ${spAccent};
  background: ${spTabBarBg};
  color: ${spTextMain};
  font-family: ${fontMono};
  font-size: 12px;
  cursor: pointer;
  letter-spacing: 0.03em;
  transition:
    background 80ms,
    border-color 80ms,
    color 80ms;
  &:hover {
    background: ${spHeaderBg};
    border-color: ${spAccentBright};
    color: #d8ecff;
  }
`;

export const modalBackdropCss = css`
  position: absolute;
  inset: 0;
  background: rgba(4, 10, 20, 0.72);
  z-index: 100;
`;

export const modalBoxCss = css`
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 101;
  width: min(420px, 90%);
  background: ${spHeaderBg};
  border: 1px solid ${spBorderStrong};
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 0;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
`;

export const modalHeaderRowCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 10px 14px;
  border-bottom: 1px solid ${spBorderSubtle};
`;

export const modalTitleCss = css`
  font-family: ${fontMono};
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: ${spTextTitle};
`;

export const modalCloseXCss = css`
  background: transparent;
  border: none;
  color: ${spTextMuted};
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  &:hover {
    color: ${spTextMain};
  }
`;

export const modalBodyCss = css`
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

export const modalTextareaCss = css`
  width: 100%;
  min-height: 80px;
  resize: vertical;
  background: ${spBg};
  border: 1px solid ${spBorderSubtle};
  border-radius: 5px;
  color: ${spTextMain};
  font-family: ${fontMono};
  font-size: 12px;
  padding: 8px 10px;
  box-sizing: border-box;
  outline: none;
  &:focus {
    border-color: ${spAccent};
  }
  &::placeholder {
    color: ${spTextDim};
  }
`;

export const modalFollowupRowCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
`;

export const modalFollowupLabelCss = css`
  font-family: ${fontMono};
  font-size: 10px;
  color: ${spTextMuted};
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-right: 2px;
`;

export const modalFollowupPillCss = (active: boolean) => css`
  height: 22px;
  padding: 0 10px;
  border-radius: 11px;
  border: 1px solid ${active ? spAccent : spBorder};
  background: ${active ? spHeaderBg : "transparent"};
  color: ${active ? spTextMain : spTextMuted};
  font-family: ${fontMono};
  font-size: 10px;
  cursor: pointer;
  &:hover {
    border-color: ${spAccentBright};
    color: ${spTextMain};
  }
`;

export const modalActionsRowCss = css`
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 14px 14px 14px;
  border-top: 1px solid ${spBorderSubtle};
`;

export const modalCancelBtnCss = css`
  height: 28px;
  padding: 0 14px;
  border-radius: 5px;
  border: 1px solid ${spBorder};
  background: transparent;
  color: ${spTextMuted};
  font-family: ${fontMono};
  font-size: 11px;
  cursor: pointer;
  &:hover {
    border-color: ${spAccent};
    color: ${spTextMain};
  }
`;

export const modalSubmitBtnCss = (disabled: boolean) => css`
  height: 28px;
  padding: 0 16px;
  border-radius: 5px;
  border: 1px solid ${disabled ? spBorder : spAccent};
  background: ${disabled ? "transparent" : spTabBarBg};
  color: ${disabled ? spTextDim : spTextMain};
  font-family: ${fontMono};
  font-size: 11px;
  cursor: ${disabled ? "not-allowed" : "pointer"};
  &:hover {
    ${disabled
      ? ""
      : `background: ${spHeaderBg}; border-color: ${spAccentBright}; color: #d8ecff;`}
  }
`;
