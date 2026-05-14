import { css } from "@emotion/react";
import _spin from "./_spin";
import scrollbarCss from "./scrollBarCss";

export const panelCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d0d;
  border-right: 1px solid #1e1e1e;
  overflow: hidden;
  flex-shrink: 0;
`;

export const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-bottom: 1px solid #1e1e1e;
  background: #111;
  flex-shrink: 0;
  min-height: 32px;
`;

export const headerTitleCss = css`
  font-family: "Consolas", monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #555;
`;

export const toggleButtonCss = css`
  background: transparent;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 13px;
  padding: 0 2px;
  line-height: 1;
  &:hover {
    color: #aaa;
  }
`;

export const collapsedStripCss = css`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  background: #0d0d0d;
  border-right: 1px solid #1e1e1e;
`;

export const collapsedLabelCss = css`
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: "Consolas", monospace;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: #484848;
  text-transform: uppercase;
`;

export const tabBarCss = css`
  display: flex;
  flex-direction: row;
  height: 30px;
  border-bottom: 1px solid #1e1e1e;
  background: #0d0d0d;
  flex-shrink: 0;
  overflow: hidden;
`;

export const tabButtonCss = (active: boolean) => css`
  flex: 1;
  height: 100%;
  background: ${active ? "#161616" : "transparent"};
  border: none;
  border-bottom: 2px solid ${active ? "#2563eb" : "transparent"};
  color: ${active ? "#b0b0b0" : "#484848"};
  padding: 0 4px;
  font-family: "Consolas", monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-align: center;
  cursor: pointer;
  transition:
    color 0.15s,
    background 0.15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  &:hover {
    color: ${active ? "#c0c0c0" : "#707070"};
    background: #141414;
  }
`;

export const tabContentAreaCss = css`
  position: relative;
  flex: 1;
  overflow: hidden;
`;

export const tabPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  padding: 10px;
  ${scrollbarCss}
`;

export const promptPanelCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  overflow-y: auto;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  padding: 10px;
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #777;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  ${scrollbarCss}
`;

export const rowCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
`;

export const skillsCardCss = css`
  border: 1px solid #1e1e1e;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 10px;
`;

export const skillsCardHeaderCss = css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #555;
  padding: 4px 8px;
  background: #111;
  border-bottom: 1px solid #1e1e1e;
`;

export const skillsCardBodyCss = css`
  ${scrollbarCss}
  max-height: 100px;
  overflow-y: auto;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

export const skillsCardPathCss = css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  color: #4a4a4a;
  word-break: break-all;
  margin-bottom: 3px;
`;

export const skillsCardFileCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #777;
`;

export const toolsCardPluginNameCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #668;
  margin-top: 3px;
`;

export const toolsCardPluginPathCss = css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  color: #3a3a4a;
  word-break: break-all;
  margin-bottom: 2px;
`;

export const toolsCardNameCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #777;
`;

export const toolsCardDividerCss = css`
  border: none;
  border-top: 1px solid #1e1e1e;
  margin: 4px 0;
`;

export const placeholderCss = css`
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #333;
  font-style: italic;
  padding: 4px 0;
`;

export const refreshSpinnerCss = css`
  display: inline-block;
  width: 9px;
  height: 9px;
  border: 1.5px solid rgba(85, 85, 85, 0.4);
  border-top-color: #888;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

export const memTabContainerCss = (visible: boolean) => css`
  position: absolute;
  inset: 0;
  opacity: ${visible ? 1 : 0};
  pointer-events: ${visible ? "auto" : "none"};
  transition: opacity 0.18s ease;
  display: flex;
  flex-direction: column;
`;

export const memTabScrollCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  ${scrollbarCss}
`;

export const memTabFooterCss = css`
  flex-shrink: 0;
  border-top: 1px solid #1a1a1a;
  padding: 0 10px;
  height: 20px;
  display: flex;
  align-items: center;
  overflow: hidden;
  background: #0a0a0a;
`;

export const saveTracesBtnCss = css`
  background: transparent;
  border: 1px solid #2a2a2a;
  color: #555;
  cursor: pointer;
  font-family: "Consolas", monospace;
  font-size: 9px;
  padding: 3px 10px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  &:hover {
    color: #aaa;
    border-color: #444;
  }
  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  &:disabled:hover {
    color: #555;
    border-color: #2a2a2a;
  }
`;

export const saveTracesStatusCss = (ok: boolean) => css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  color: ${ok ? "#5a8a5a" : "#8a3535"};
  margin-top: 4px;
  word-break: break-all;
`;

export const modalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

export const modalCardCss = css`
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  width: 600px;
  max-width: 90vw;
  max-height: 80vh;
  overflow: hidden;
`;

export const modalHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #1e1e1e;
  flex-shrink: 0;
  gap: 8px;
`;

export const modalTitleCss = css`
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #888;
  word-break: break-all;
  flex: 1;
  min-width: 0;
`;

export const modalCloseButtonCss = css`
  background: transparent;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
  &:hover {
    color: #aaa;
  }
`;

export const modalBodyCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #888;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  ${scrollbarCss}
`;

export const modalLoadingWrapCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px 0;
`;

export const modalSpinnerCss = css`
  width: 18px;
  height: 18px;
  border: 2px solid rgba(136, 136, 136, 0.2);
  border-top-color: #777;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

export const modalFooterCss = css`
  flex-shrink: 0;
  border-top: 1px solid #1e1e1e;
  padding: 5px 12px;
  font-family: "Consolas", monospace;
  font-size: 10px;
`;

export const modalFooterModifiedCss = css`
  color: #9a6020;
  cursor: pointer;
  &:hover {
    color: #c07828;
  }
`;

export const modalFooterDeletedCss = css`
  color: #7a3030;
`;
