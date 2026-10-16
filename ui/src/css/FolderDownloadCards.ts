import { css, keyframes } from "@emotion/react";

const slideIn = keyframes`
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
`;

const indeterminate = keyframes`
  from { transform: translateX(-100%); }
  to { transform: translateX(260%); }
`;

export const downloadCardsCss = css`
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 100;
  width: min(380px, calc(100vw - 36px));
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
`;

export const downloadCardCss = (failed: boolean) => css`
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 10px;
  padding: 13px 14px;
  border: 1px solid ${failed ? "#6b3035" : "#30405f"};
  border-radius: 8px;
  background: #111923;
  color: #e6edf7;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.48);
  animation: ${slideIn} 0.16s ease-out;
`;

export const downloadStatusIconCss = (failed: boolean) => css`
  margin-top: 1px;
  color: ${failed ? "#e2757b" : "#7da9da"};
`;

export const downloadCardTitleCss = css`
  overflow: hidden;
  color: #f3f6ff;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export const downloadDetailCss = css`
  margin-top: 4px;
  color: #94a6bd;
  font-family: Consolas, "Courier New", monospace;
  font-size: 11px;
  line-height: 1.35;
`;

export const downloadProgressTrackCss = css`
  height: 4px;
  margin-top: 9px;
  overflow: hidden;
  border-radius: 999px;
  background: #253247;
`;

export const downloadProgressFillCss = (progress: number | null) => css`
  width: ${progress === null ? "38%" : `${progress}%`};
  height: 100%;
  border-radius: inherit;
  background: #4f8cc9;
  transition: width 0.2s ease;
  animation: ${progress === null
    ? `${indeterminate} 1.1s ease-in-out infinite`
    : "none"};
`;
