// Styles for AgentSettingsDialog (mirrors HeartbeatSettingsDialog.tsx's dialog
// conventions).
import { css } from "@emotion/react";

export const backdropCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

export const dialogCss = css`
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 28px 32px;
  width: 480px;
  max-width: 95vw;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
  font-family: "Fira Code", "Consolas", monospace;
  color: #d0d0d0;
`;

export const dialogTitleCss = css`
  font-size: 15px;
  font-weight: 600;
  color: #c8c8c8;
  letter-spacing: 1px;
`;

export const fieldLabelCss = css`
  font-size: 11px;
  color: #666;
  margin-bottom: 6px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
`;

export const controlCss = css`
  width: 100%;
  box-sizing: border-box;
  background: #0f0f0f;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  &:focus {
    border-color: #3a3a5a;
  }
  &:read-only {
    color: #8a8a8a;
    background: #161616;
  }
`;

export const textareaCss = css`
  ${controlCss};
  resize: vertical;
  min-height: 90px;
`;

export const hintCss = css`
  font-size: 10px;
  color: #555;
  margin-top: 4px;
`;

export const fieldErrorCss = css`
  font-size: 11px;
  color: #e05555;
  margin-top: 5px;
`;

export const checkboxRowCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 12px;
  color: #c0c0c0;
  & input {
    accent-color: #5577ee;
    cursor: pointer;
  }
`;

export const footerCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
`;

export const secondaryBtnCss = css`
  background: none;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #888;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 16px;
  cursor: pointer;
`;

export const dangerBtnCss = css`
  ${secondaryBtnCss};
  color: #cc6666;
  border-color: #3a1a1a;
  margin-right: auto;
`;

export const saveBtnCss = (disabled: boolean) => css`
  background: ${disabled ? "#1a1a2e" : "#1e2650"};
  border: 1px solid ${disabled ? "#2a3a6e" : "#3a5aee"};
  border-radius: 5px;
  color: ${disabled ? "#5566aa" : "#8aacff"};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 20px;
  cursor: ${disabled ? "not-allowed" : "pointer"};
`;

export const errorMsgCss = css`
  font-size: 11px;
  color: #cc6666;
  background: #1a0a0a;
  border: 1px solid #3a1a1a;
  border-radius: 4px;
  padding: 8px 12px;
`;

export const fieldCss = css`
  display: flex;
  flex-direction: column;
`;
