import { css } from "@emotion/react";

// Styles for FolderBrowserDialog.tsx. Colors follow NewSessionDialog.

export const browserBackdropCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
`;

export const browserDialogCss = css`
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  width: 760px;
  max-width: 95vw;
  height: 70vh;
  max-height: 640px;
  display: flex;
  flex-direction: column;
  font-family: "Fira Code", "Consolas", monospace;
  color: #d0d0d0;
  overflow: hidden;
`;

export const browserHeaderCss = css`
  padding: 16px 18px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid #1f1f1f;
`;

export const browserTitleCss = css`
  font-size: 13px;
  font-weight: 600;
  color: #c8c8c8;
  letter-spacing: 1px;
`;

export const pathRowCss = css`
  display: flex;
  gap: 6px;
`;

export const pathInputCss = (hasError: boolean) => css`
  flex: 1;
  min-width: 0;
  background: #0f0f0f;
  border: 1px solid ${hasError ? "#7a2a2a" : "#2a2a2a"};
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 6px 8px;
  outline: none;
  &:focus {
    border-color: ${hasError ? "#aa3a3a" : "#3a3a5a"};
  }
`;

export const smallBtnCss = css`
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #888;
  font-family: inherit;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  &:hover:not(:disabled) {
    border-color: #444;
  }
  &:disabled {
    color: #444;
    cursor: not-allowed;
  }
`;

export const navErrorCss = css`
  font-size: 10px;
  color: #cc6666;
`;

export const crumbsCss = css`
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  font-size: 11px;
  color: #555;
`;

export const crumbBtnCss = css`
  background: none;
  border: none;
  color: #7a8acc;
  font-family: inherit;
  font-size: 11px;
  padding: 0 2px;
  cursor: pointer;
  &:hover {
    text-decoration: underline;
  }
`;

export const browserBodyCss = css`
  flex: 1;
  min-height: 0;
  display: flex;
`;

export const sidebarCss = css`
  width: 170px;
  flex-shrink: 0;
  border-right: 1px solid #1f1f1f;
  padding: 8px 6px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

export const shortcutBtnCss = (active: boolean) => css`
  text-align: left;
  background: ${active ? "#1e2650" : "none"};
  border: 1px solid ${active ? "#3a5aee" : "transparent"};
  border-radius: 5px;
  color: ${active ? "#8aacff" : "#999"};
  font-family: inherit;
  font-size: 12px;
  padding: 6px 8px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  &:hover {
    background: ${active ? "#1e2650" : "#1a1a1a"};
  }
`;

export const listCss = css`
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 6px;
  &::-webkit-scrollbar {
    width: 5px;
  }
  &::-webkit-scrollbar-thumb {
    background: #3a3a3a;
    border-radius: 3px;
  }
`;

export const entryBtnCss = (selected: boolean) => css`
  display: block;
  width: 100%;
  text-align: left;
  background: ${selected ? "#1e2650" : "none"};
  border: 1px solid ${selected ? "#3a5aee" : "transparent"};
  border-radius: 4px;
  color: ${selected ? "#8aacff" : "#c0c0c0"};
  font-family: inherit;
  font-size: 12px;
  padding: 5px 8px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: none;
  &:hover {
    background: ${selected ? "#1e2650" : "#1a1a1a"};
  }
`;

export const listNoteCss = css`
  font-size: 11px;
  color: #555;
  padding: 8px;
`;

export const browserFooterCss = css`
  border-top: 1px solid #1f1f1f;
  padding: 10px 18px;
  display: flex;
  align-items: center;
  gap: 10px;
`;

export const hiddenToggleCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #777;
  cursor: pointer;
  input {
    accent-color: #5577ee;
  }
`;

export const selectionCss = css`
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: #666;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
`;
