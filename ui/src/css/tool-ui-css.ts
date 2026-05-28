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
  min-width: 0;
  overflow: hidden;
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
  min-height: calc(10px + 28px + 10px);
`;

export const expandButtonCss = css`
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  padding: 0;
  background: rgba(18, 6, 34, 0.78);
  backdrop-filter: blur(8px) saturate(1.5);
  -webkit-backdrop-filter: blur(8px) saturate(1.5);
  border: 1px solid rgba(138, 106, 186, 0.55);
  border-radius: 4px;
  color: #c4a0f0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  box-shadow:
    0 2px 8px rgba(0, 0, 0, 0.55),
    inset 0 1px 0 rgba(210, 170, 255, 0.13);
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
  &:hover {
    background: rgba(35, 12, 62, 0.88);
    color: #d8b8ff;
    border-color: rgba(180, 139, 224, 0.75);
  }
`;
