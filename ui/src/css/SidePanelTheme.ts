import { css } from "@emotion/react";

// Shared visual language for the auxiliary side panels (Debug panel, Terminal
// panel). Both panels draw their backgrounds/borders/text colors from here so
// they read as one system rather than two different UIs bolted together.

export const fontMono = `"Consolas", monospace`;

// Backgrounds
export const spBg = "#080f18";
export const spHeaderBg = "#0b1521";
export const spTabBarBg = "#09111c";
export const spDividerBg = "#0e1f33";
export const spDividerBgHover = "#15304d";

// Borders
export const spBorder = "#1a2a40";
export const spBorderSubtle = "#17283c";
export const spBorderStrong = "#2a4a6a";
export const spAccent = "#3d6b99";
export const spAccentBright = "#4d86bf";

// Text — one consistent scale used by both panels:
//   spTextMain   – primary/readable content (values, active state)
//   spTextTitle  – section headers, panel title, uppercase labels
//   spTextMuted  – secondary/de-emphasized but still legible
//   spTextDim    – least prominent (placeholders, disabled, empty states)
export const spTextMain = "#c9def2";
export const spTextTitle = "#8fb0d0";
export const spTextMuted = "#6c88a4";
export const spTextDim = "#4f6a82";

export const panelRootCss = css`
  display: flex;
  flex-direction: row;
  height: 100%;
  overflow: hidden;
`;

export const dividerCss = css`
  width: 28px;
  flex-shrink: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: ${spDividerBg};
  cursor: pointer;
  user-select: none;
  transition: background 0.12s ease;
  &:hover {
    background: ${spDividerBgHover};
  }
  &:focus-visible {
    outline: 2px solid ${spAccentBright};
    outline-offset: -2px;
  }
`;

export const dividerIconWrapCss = css`
  display: flex;
  color: ${spTextMain};
  flex-shrink: 0;
`;

export const dividerLabelCss = css`
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: ${fontMono};
  font-size: 12px;
  letter-spacing: 0.12em;
  color: ${spTextMain};
  text-transform: uppercase;
`;

export const dividerBadgeCss = css`
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  background: ${spHeaderBg};
  border: 1px solid ${spAccent};
  color: ${spTextMain};
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: ${fontMono};
  font-size: 10px;
  flex-shrink: 0;
`;
