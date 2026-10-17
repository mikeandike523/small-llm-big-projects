import { css } from "@emotion/react";
import {
  fontMono,
  spAccent,
  spAccentBright,
  spBg,
  spBorder,
  spBorderStrong,
  spTextDim,
  spTextMain,
  spTextMuted,
} from "../../css/SidePanelTheme";

const barCss = css`
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 6px 4px;
  border-bottom: 1px solid ${spBorder};
`;

const inputRowCss = css`
  display: flex;
  gap: 4px;
  min-width: 0;
`;

const inputCss = css`
  flex: 1 1 0;
  min-width: 0;
  background: ${spBg};
  color: ${spTextMain};
  border: 1px solid ${spBorderStrong};
  border-radius: 3px;
  font-family: ${fontMono};
  font-size: 10px;
  padding: 2px 5px;
  outline: none;
  &::placeholder {
    color: ${spTextDim};
  }
  &:focus {
    border-color: ${spAccentBright};
  }
`;

const buttonCss = (highlighted: boolean) => css`
  flex: 0 0 auto;
  background: ${highlighted ? spAccent : "#19283b"};
  color: ${highlighted ? "#fff" : "#6b9fe4"};
  border: 1px solid ${highlighted ? spAccentBright : "#2b4a70"};
  border-radius: 3px;
  font-size: 10px;
  font-family: inherit;
  padding: 1px 7px;
  cursor: pointer;
  &:hover:not(:disabled) {
    background: ${highlighted ? spAccentBright : "#26364d"};
  }
  &:disabled {
    opacity: 0.4;
    cursor: default;
  }
`;

const statusCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  color: ${spTextMuted};
`;

export default function BackendLogFilterBar({
  text,
  label,
  onTextChange,
  onLabelChange,
  onApply,
  onClear,
  pending,
  filtered,
  matchCount,
  totalCount,
}: {
  text: string;
  label: string;
  onTextChange: (value: string) => void;
  onLabelChange: (value: string) => void;
  onApply: () => void;
  onClear: () => void;
  // Drafts differ from the applied filter.
  pending: boolean;
  // A filter is currently applied.
  filtered: boolean;
  matchCount: number;
  totalCount: number;
}) {
  const applyOnEnter = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") onApply();
  };
  const canClear = filtered || text !== "" || label !== "";

  return (
    <div css={barCss}>
      <div css={inputRowCss}>
        <input
          css={inputCss}
          value={text}
          placeholder="Filter text…"
          spellCheck={false}
          onChange={(event) => onTextChange(event.target.value)}
          onKeyDown={applyOnEnter}
        />
        <input
          css={inputCss}
          value={label}
          placeholder="Filter row 1…"
          title="Matches the first row of grouped (multi-row) log entries"
          spellCheck={false}
          onChange={(event) => onLabelChange(event.target.value)}
          onKeyDown={applyOnEnter}
        />
        <button
          css={buttonCss(pending)}
          onClick={onApply}
          title="Apply filters and jump to the newest log"
        >
          Apply
        </button>
        <button
          css={buttonCss(false)}
          onClick={onClear}
          disabled={!canClear}
          title="Clear filters"
        >
          ×
        </button>
      </div>
      <div css={statusCss}>
        {filtered
          ? `${matchCount} ${matchCount === 1 ? "match" : "matches"} in last ${totalCount} logs`
          : `${totalCount} logs`}
        {pending ? " · not applied" : ""}
      </div>
    </div>
  );
}
