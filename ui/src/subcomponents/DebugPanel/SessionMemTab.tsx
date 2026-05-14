import { css } from "@emotion/react";
import { refreshSpinnerCss, placeholderCss } from "../../css/DebugPanel";

export const sessionToolbarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
`;

export const sessionKeyCountCss = css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #444;
`;

export const refreshButtonCss = css`
  background: transparent;
  border: 1px solid #2a2a2a;
  color: #555;
  cursor: pointer;
  font-family: "Consolas", monospace;
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
    color: #aaa;
    border-color: #444;
  }
  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  &:disabled:hover {
    color: #555;
    border-color: #2a2a2a;
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
  border: 1px solid #1a1a1a;
  border-radius: 3px;
  &:hover {
    border-color: #2a2a2a;
    background: #111;
  }
`;

export const memKeyNameCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #888;
  word-break: break-all;
  flex: 1;
  min-width: 0;
`;

export const viewButtonCss = css`
  background: transparent;
  border: 1px solid #2a2a2a;
  color: #555;
  cursor: pointer;
  font-family: "Consolas", monospace;
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  margin-left: 6px;
  &:hover {
    color: #aaa;
    border-color: #444;
  }
`;

export const dirtyAsteriskCss = css`
  color: #c07828;
  font-size: 11px;
  margin-left: 4px;
  flex-shrink: 0;
`;

export default function SessionMemTab({
  keys,
  dirtyMemKeys,
  onRefresh,
  onView,
  loading,
}: {
  keys: string[];
  dirtyMemKeys: Set<string>;
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
                  <span css={dirtyAsteriskCss} title="Modified since last read">
                    *
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
