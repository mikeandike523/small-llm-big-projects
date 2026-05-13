import {
  sessionToolbarCss,
  sessionKeyCountCss,
  refreshButtonCss,
  refreshSpinnerCss,
  placeholderCss,
  memKeyListCss,
  memKeyRowCss,
  memKeyNameCss,
  dirtyAsteriskCss,
  viewButtonCss,
} from "../../css/DebugPanel";

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
