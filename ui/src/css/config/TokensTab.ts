// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

import { css } from "@emotion/react";

export const containerCss = css`
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

export const topBarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

export const addBtnCss = css`
  background: #1a1a2e;
  color: #7b9cff;
  border: 1px solid #2a3a6e;
  border-radius: 6px;
  padding: 7px 16px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  &:hover {
    background: #222244;
    border-color: #4a6aee;
  }
`;

export const errorBannerCss = css`
  background: #1a0a0a;
  border: 1px solid #3a1a1a;
  border-radius: 6px;
  padding: 10px 14px;
  color: #cc6666;
  font-size: 12px;
`;

export const tableWrapCss = css`
  overflow-x: auto;
  border: 1px solid #222;
  border-radius: 6px;
`;

export const tableCss = css`
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-family: "Fira Code", "Consolas", monospace;
`;

export const thCss = css`
  background: #111;
  color: #8a9ab8;
  text-align: left;
  padding: 9px 12px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 1px solid #222;
  white-space: nowrap;
`;

export const tdCss = css`
  padding: 8px 12px;
  border-bottom: 1px solid #1a1a1a;
  color: #e0e0e0;
  vertical-align: middle;
`;

export const activeTrCss = css`
  background: #1a2a1a;
`;

export const inputCss = css`
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  color: #e0e0e0;
  font-family: "Fira Code", "Consolas", monospace;
  font-size: 12px;
  padding: 5px 8px;
  width: 100%;
  outline: none;
  min-width: 80px;
  &:focus {
    border-color: #4a6aee;
  }
`;

export const iconBtnCss = css`
  background: none;
  border: none;
  cursor: pointer;
  color: #6a8ab8;
  font-size: 13px;
  padding: 3px 5px;
  border-radius: 4px;
  line-height: 1;
  &:hover {
    color: #aac4ee;
    background: #1a2a3a;
  }
  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

export const rotateBtnCss = css`
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  color: #8a9ab8;
  font-size: 11px;
  font-family: inherit;
  padding: 3px 8px;
  cursor: pointer;
  white-space: nowrap;
  &:hover {
    border-color: #4a6aee;
    color: #aac4ee;
  }
`;

export const deleteBtnCss = css`
  background: none;
  border: none;
  cursor: pointer;
  color: #884444;
  font-size: 13px;
  padding: 3px 5px;
  border-radius: 4px;
  line-height: 1;
  &:hover {
    color: #cc4444;
    background: #2a0a0a;
  }
`;

export const confirmDeleteCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
`;

export const yesDeleteBtnCss = css`
  background: #2a0a0a;
  border: 1px solid #cc2222;
  border-radius: 4px;
  color: #ee4444;
  font-size: 11px;
  font-family: inherit;
  padding: 3px 8px;
  cursor: pointer;
  &:hover {
    background: #3a0a0a;
  }
`;

export const noBtnCss = css`
  background: none;
  border: 1px solid #333;
  border-radius: 4px;
  color: #8a9ab8;
  font-size: 11px;
  font-family: inherit;
  padding: 3px 8px;
  cursor: pointer;
  &:hover {
    border-color: #556;
  }
`;

export const actionsCss = css`
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
`;

export const activeLabelCss = css`
  font-size: 10px;
  color: #3ccc6c;
  border: 1px solid #2a4a2a;
  border-radius: 3px;
  padding: 1px 5px;
  margin-left: 6px;
`;
