import { css } from "@emotion/react";
import scrollbarCss from "./scrollBarCss";
import _spin from "./_spin";

export const appLayoutCss = css`
  display: flex;
  flex-direction: row;
  height: 100vh;
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 15px;
  background: #0f0f0f;
  color: #e0e0e0;
`;

export const debugPanelWrapperCss = (open: boolean) => css`
  width: ${open ? "20%" : "28px"};
  min-width: ${open ? "160px" : "28px"};
  max-width: ${open ? "320px" : "28px"};
  transition:
    width 0.2s ease,
    min-width 0.2s ease,
    max-width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  height: 100%;
`;

export const terminalPanelWrapperCss = (open: boolean) => css`
  width: ${open ? "38%" : "28px"};
  min-width: ${open ? "280px" : "28px"};
  max-width: ${open ? "680px" : "28px"};
  transition:
    width 0.2s ease,
    min-width 0.2s ease,
    max-width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  height: 100%;
`;

export const mainAreaCss = css`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
`;

export const threadCss = css`
  ${scrollbarCss}
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 28px;
`;

export const inputBarCss = css`
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #22304d;
  background: #101722;
`;

export const textareaCss = css`
  flex: 1;
  background: #101722;
  color: #f3f6ff;
  border: 1px solid #30405f;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
  &:focus {
    border-color: #8aa4d8;
  }
`;

export const sendButtonCss = css`
  position: relative;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 20px;
  font-size: 14px;
  cursor: pointer;
  align-self: flex-end;
  height: 40px;
  overflow: hidden;
  &:disabled {
    background: #1e3a6e;
    cursor: not-allowed;
  }
`;

export const stopButtonCss = css`
  background: #1a0a0a;
  color: #c06060;
  border: 1px solid #4a1818;
  border-radius: 8px;
  padding: 0 16px;
  font-size: 14px;
  cursor: pointer;
  font-family: inherit;
  height: 40px;
  align-self: flex-end;
  transition:
    background 0.15s,
    border-color 0.15s;
  &:hover {
    background: #2a1010;
    border-color: #6a2424;
  }
  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

export const spinnerCss = css`
  position: absolute;
  inset: 0;
  margin: auto;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

export const headerBarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid #1d2940;
  flex-shrink: 0;
  gap: 12px;
`;

export const headerSideCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
`;

export const sessionCostCss = css`
  font-size: 10px;
  color: #6a9060;
  font-family: "Consolas", monospace;
  white-space: nowrap;
`;

export const statusCss = css`
  font-size: 11px;
  color: #f2f6ff;
  font-family: "Consolas", monospace;
  white-space: nowrap;
`;

export const sessionIdCss = css`
  font-size: 10px;
  color: #dbe5ff;
  font-family: "Consolas", monospace;
  white-space: nowrap;
  cursor: default;
`;

export const dashboardButtonCss = css`
  background: #101722;
  color: #f3f6ff;
  border: 1px solid #30405f;
  border-radius: 999px;
  width: 28px;
  height: 28px;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition:
    background 0.15s,
    border-color 0.15s,
    transform 0.15s;
  &:hover {
    background: #172235;
    border-color: #6f8fc5;
    transform: translateX(-1px);
  }
`;

// Follow-up behavior footer (below input bar)
export const followupFooterCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 16px 6px;
  background: #101722;
  border-top: 1px solid #1a2535;
`;

export const followupLabelCss = css`
  font-size: 11px;
  color: #4a6080;
  white-space: nowrap;
  flex-shrink: 0;
`;

export const followupOptionCss = (active: boolean) => css`
  background: ${active ? "#1a2f4a" : "transparent"};
  color: ${active ? "#7aaad4" : "#3a5070"};
  border: 1px solid ${active ? "#2a4a6a" : "#1e2e40"};
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 0.1s,
    color 0.1s,
    border-color 0.1s;
  &:hover {
    background: #162840;
    color: #6090b8;
    border-color: #253a52;
  }
`;
