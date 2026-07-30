import { css } from "@emotion/react";
import { refreshSpinnerCss, placeholderCss } from "../../css/DebugPanel";
import {
  fontMono,
  spAccent,
  spAccentBright,
  spBorder,
  spHeaderBg,
  spTextMain,
  spTextMuted,
  spTextTitle,
} from "../../css/SidePanelTheme";

export const sessionToolbarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
`;

export const sessionKeyCountCss = css`
  font-family: ${fontMono};
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: ${spTextTitle};
`;

export const refreshButtonCss = css`
  background: transparent;
  border: 1px solid ${spBorder};
  color: ${spTextMuted};
  cursor: pointer;
  font-family: ${fontMono};
  font-size: 9px;
  padding: 2px 8px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  min-width: 52px;
  text-align: center;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  &:hover {
    color: ${spTextMain};
    border-color: ${spAccentBright};
  }
  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  &:disabled:hover {
    color: ${spTextMuted};
    border-color: ${spBorder};
  }
`;

export const memKeyListCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

export const memKeyRowCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 6px;
  border: 1px solid ${spBorder};
  border-radius: 3px;
  &:hover {
    border-color: ${spAccent};
    background: ${spHeaderBg};
  }
`;

export const memKeyNameCss = css`
  font-family: ${fontMono};
  font-size: 10px;
  color: ${spTextMain};
  word-break: break-all;
  flex: 1;
  min-width: 0;
`;

export const viewButtonCss = css`
  background: transparent;
  border: 1px solid ${spBorder};
  color: ${spTextMuted};
  cursor: pointer;
  font-family: ${fontMono};
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  margin-left: 6px;
  &:hover {
    color: ${spTextMain};
    border-color: ${spAccentBright};
  }
`;

export const dirtyTagCss = css`
  color: #d89552;
  font-size: 9px;
  margin-left: 5px;
  flex-shrink: 0;
  font-family: ${fontMono};
`;

export const seenTagCss = css`
  color: #74b088;
  font-size: 9px;
  margin-left: 5px;
  flex-shrink: 0;
  font-family: ${fontMono};
`;

export default function SessionMemTab({
  keys,
  dirtyMemKeys,
  seenMemKeys,
  onRefresh,
  onView,
  loading,
}: {
  keys: string[];
  dirtyMemKeys: Set<string>;
  seenMemKeys: Set<string>;
  onRefresh: () => void;
  onView: (key: string) => void;
  loading: boolean;
}) {
  return (
    <>
      <div css={sessionToolbarCss}>
        <span css={sessionKeyCountCss}>
          {keys.length} key{keys.length !== 1 ? "s" : ""}
        </span>
        <button css={refreshButtonCss} onClick={onRefresh} disabled={loading}>
          {loading ? <span css={refreshSpinnerCss} /> : "Refresh"}
        </button>
      </div>
      {keys.length === 0 ? (
        <div css={placeholderCss}>No memory keys.</div>
      ) : (
        <div css={memKeyListCss}>
          {keys.map((key) => (
            <div key={key} css={memKeyRowCss}>
              <span css={memKeyNameCss}>
                {key}
                {dirtyMemKeys.has(key) && (
                  <span css={dirtyTagCss} title="Modified since last read">
                    (dirty)
                  </span>
                )}
                {seenMemKeys.has(key) && (
                  <span css={seenTagCss} title="Read at least once">
                    (seen)
                  </span>
                )}
              </span>
              <button css={viewButtonCss} onClick={() => onView(key)}>
                View
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
