import { css } from "@emotion/react";

export const viewFullButtonCss = css`
  background: transparent;
  color: #8860c0;
  border: 1px solid #4a2a7a;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  white-space: nowrap;
  flex-shrink: 0;
  transition:
    background 0.15s,
    color 0.15s;
  &:hover {
    background: #3a1a5a;
    color: #c090f0;
  }
`;

export const toolCallCss = css`
  flex-shrink: 0;
  border: 1px solid #3d2f5a;
  border-radius: 10px;
  overflow: hidden;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
`;

export const toolHeaderCss = css`
  background: #2a1a4a;
  color: #b48be0;
  padding: 8px 14px;
  font-family: "Consolas", monospace;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
`;

export const toolArgsCss = css`
  background: #16162a;
  padding: 8px 14px;
  border-top: 1px solid #252545;
`;

export const toolResultCss = css`
  background: #0a1a0a;
  color: #7ec87e;
  padding: 8px 14px;
  font-family: "Consolas", monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #1a3a1a;
  & code {
    display: block;
    font-family: inherit;
    background: transparent;
    padding: 0;
    margin: 0;
  }
`;

export const toolResultContainerCss = css`
  position: relative;
  min-height: 120px;
`;

export const expandButtonCss = css`
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  padding: 0;
  background: rgba(136, 96, 192, 0.15);
  border: 1px solid #6a4a9a;
  border-radius: 4px;
  color: #b48be0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
  &:hover {
    background: rgba(136, 96, 192, 0.3);
    color: #d4b0ff;
    border-color: #8a6aba;
  }
`;
