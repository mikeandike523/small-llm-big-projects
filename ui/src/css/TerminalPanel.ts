import { css, keyframes } from "@emotion/react";

export const panelCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #080f18;
  border-left: 1px solid #1a2a40;
  overflow: hidden;
  position: relative;
`;

export const collapsedStripCss = css`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  background: #080f18;
`;

export const collapsedLabelCss = css`
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: "Consolas", monospace;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: #54708f;
  text-transform: uppercase;
`;

export const toggleButtonCss = css`
  background: transparent;
  border: none;
  color: #7193b6;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 2px;
  &:hover {
    color: #b9d3ee;
  }
`;

export const badgeCss = css`
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  background: #14263b;
  border: 1px solid #294a70;
  color: #9dbce0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: "Consolas", monospace;
  font-size: 10px;
`;

export const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 34px;
  padding: 0 8px;
  background: #0b1521;
  border-bottom: 1px solid #17283c;
  flex-shrink: 0;
`;

export const titleCss = css`
  font-family: "Consolas", monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #88a8c8;
`;

export const tabBarCss = css`
  display: flex;
  align-items: flex-end;
  gap: 4px;
  min-height: 36px;
  padding: 5px 8px 0 8px;
  border-bottom: 1px solid #2a4a6a;
  background: #09111c;
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
  border: 1px solid ${active ? "#3d6b99" : "#1e344d"};
  border-bottom-color: ${active ? "#0d0d0d" : "#2a4a6a"};
  background: ${active ? "#0d0d0d" : "#0b1521"};
  color: ${exited ? "#55697a" : active ? "#d8ecff" : "#7fa0bc"};
  font-family: "Consolas", monospace;
  font-size: 11px;
  cursor: pointer;
  margin-bottom: -1px;
  position: relative;
  z-index: ${active ? 1 : 0};
  &:hover {
    border-color: #4d7ba8;
    border-bottom-color: ${active ? "#0d0d0d" : "#2a4a6a"};
    color: ${exited ? "#55697a" : "#b8d8f4"};
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
  border: 1px solid #24415f;
  background: #0c1f32;
  color: #a9c4df;
  font-family: "Consolas", monospace;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  &:hover {
    background: #14304b;
    border-color: #477bb0;
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
  color: #4f647b;
  font-family: "Consolas", monospace;
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
  background: #0e1f33;
  border: 1px solid #2a4a6a;
  border-radius: 4px;
  color: #a8c8e8;
  font-family: "Consolas", monospace;
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
  background: #091525;
  border-top: 1px solid #17283c;
  flex-shrink: 0;
`;

export const askButtonCss = css`
  height: 30px;
  padding: 0 18px;
  border-radius: 6px;
  border: 1px solid #2d5580;
  background: #0f2540;
  color: #8fc6f0;
  font-family: "Consolas", monospace;
  font-size: 12px;
  cursor: pointer;
  letter-spacing: 0.03em;
  transition:
    background 80ms,
    border-color 80ms,
    color 80ms;
  &:hover {
    background: #163353;
    border-color: #4d86bf;
    color: #c0dff8;
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
  background: #0b1b2e;
  border: 1px solid #2a4a6a;
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
  border-bottom: 1px solid #1e3651;
`;

export const modalTitleCss = css`
  font-family: "Consolas", monospace;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #88a8c8;
`;

export const modalCloseXCss = css`
  background: transparent;
  border: none;
  color: #54708f;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  &:hover {
    color: #b9d3ee;
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
  background: #07111e;
  border: 1px solid #1e3651;
  border-radius: 5px;
  color: #c8dff0;
  font-family: "Consolas", monospace;
  font-size: 12px;
  padding: 8px 10px;
  box-sizing: border-box;
  outline: none;
  &:focus {
    border-color: #3d6b99;
  }
  &::placeholder {
    color: #3f5a72;
  }
`;

export const modalFollowupRowCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
`;

export const modalFollowupLabelCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #4f6a82;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-right: 2px;
`;

export const modalFollowupPillCss = (active: boolean) => css`
  height: 22px;
  padding: 0 10px;
  border-radius: 11px;
  border: 1px solid ${active ? "#3d6b99" : "#1e344d"};
  background: ${active ? "#0f2a48" : "transparent"};
  color: ${active ? "#a8d0f0" : "#4f6a82"};
  font-family: "Consolas", monospace;
  font-size: 10px;
  cursor: pointer;
  &:hover {
    border-color: #4d7ba8;
    color: #8ab8e0;
  }
`;

export const modalActionsRowCss = css`
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 14px 14px 14px;
  border-top: 1px solid #1e3651;
`;

export const modalCancelBtnCss = css`
  height: 28px;
  padding: 0 14px;
  border-radius: 5px;
  border: 1px solid #1e344d;
  background: transparent;
  color: #6a8aaa;
  font-family: "Consolas", monospace;
  font-size: 11px;
  cursor: pointer;
  &:hover {
    border-color: #3d6b99;
    color: #9dbce0;
  }
`;

export const modalSubmitBtnCss = (disabled: boolean) => css`
  height: 28px;
  padding: 0 16px;
  border-radius: 5px;
  border: 1px solid ${disabled ? "#1e344d" : "#2d6fa0"};
  background: ${disabled ? "transparent" : "#0f2f52"};
  color: ${disabled ? "#3a5570" : "#7fc0f0"};
  font-family: "Consolas", monospace;
  font-size: 11px;
  cursor: ${disabled ? "not-allowed" : "pointer"};
  &:hover {
    ${disabled
      ? ""
      : "background: #163d68; border-color: #4d86c0; color: #aad8ff;"}
  }
`;
