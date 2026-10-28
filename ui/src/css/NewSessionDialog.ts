import { css } from "@emotion/react";

// Styles for NewSessionDialog.tsx.

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
  &::-webkit-scrollbar {
    width: 5px;
  }
  &::-webkit-scrollbar-track {
    background: #0a0a0a;
  }
  &::-webkit-scrollbar-thumb {
    background: #3a3a3a;
    border-radius: 3px;
  }
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

export const cwdRowCss = css`
  display: flex;
  gap: 8px;
  align-items: stretch;
`;

export const cwdInputCss = (hasError: boolean) => css`
  flex: 1;
  background: #0f0f0f;
  border: 1px solid ${hasError ? "#7a2a2a" : "#2a2a2a"};
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  &:focus {
    border-color: ${hasError ? "#aa3a3a" : "#3a3a5a"};
  }
`;

export const cwdErrorCss = css`
  font-size: 10px;
  color: #cc6666;
  margin-top: 5px;
`;

export const browseBtnCss = (loading: boolean) => css`
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: ${loading ? "#444" : "#888"};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 12px;
  cursor: ${loading ? "not-allowed" : "pointer"};
  white-space: nowrap;
  transition: border-color 0.12s;
  &:hover {
    border-color: ${loading ? "#2a2a2a" : "#444"};
  }
`;

export const checkboxSectionCss = css`
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

export const checkboxRowCss = css`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
`;

export const checkboxInputCss = css`
  margin-top: 2px;
  accent-color: #5577ee;
  cursor: pointer;
  flex-shrink: 0;
`;

export const checkboxTextCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

export const checkboxLabelCss = css`
  font-size: 12px;
  color: #c0c0c0;
`;

export const checkboxDescCss = css`
  font-size: 10px;
  color: #444;
`;

export const footerCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
`;

export const cancelBtnCss = css`
  background: none;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #666;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 16px;
  cursor: pointer;
  &:hover {
    border-color: #444;
    color: #888;
  }
`;

export const createBtnCss = (loading: boolean) => css`
  background: ${loading ? "#1a1a2e" : "#1e2650"};
  border: 1px solid ${loading ? "#2a3a6e" : "#3a5aee"};
  border-radius: 5px;
  color: ${loading ? "#5566aa" : "#8aacff"};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 20px;
  cursor: ${loading ? "not-allowed" : "pointer"};
  transition: background 0.12s;
  &:hover {
    background: ${loading ? "#1a1a2e" : "#222a5e"};
  }
`;

export const errorMsgCss = css`
  font-size: 11px;
  color: #cc6666;
  background: #1a0a0a;
  border: 1px solid #3a1a1a;
  border-radius: 4px;
  padding: 8px 12px;
`;

export const selectCss = css`
  width: 100%;
  background: #0f0f0f;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  cursor: pointer;
  outline: none;
  &:focus {
    border-color: #3a3a5a;
  }
`;

export const warningMsgCss = css`
  font-size: 11px;
  color: #d8b45a;
  background: #1a1608;
  border: 1px solid #4a3c14;
  border-radius: 4px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  div {
    font-size: 10px;
    color: #8a7640;
  }
`;

export const proceedBtnCss = (loading: boolean) => css`
  background: ${loading ? "#1e1a0c" : "#2a2410"};
  border: 1px solid ${loading ? "#4a4020" : "#b8922a"};
  border-radius: 5px;
  color: ${loading ? "#7a6a3a" : "#f0c860"};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 20px;
  cursor: ${loading ? "not-allowed" : "pointer"};
  transition: background 0.12s;
  &:hover {
    background: ${loading ? "#1e1a0c" : "#3a3214"};
  }
`;
