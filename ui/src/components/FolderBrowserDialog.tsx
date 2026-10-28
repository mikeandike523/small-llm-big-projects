/** @jsxImportSource @emotion/react */
import { useEffect } from "react";
import { breadcrumbs, useFolderBrowser } from "../hooks/useFolderBrowser";
import { cancelBtnCss, createBtnCss } from "../css/NewSessionDialog";
import {
  browserBackdropCss,
  browserBodyCss,
  browserDialogCss,
  browserFooterCss,
  browserHeaderCss,
  browserTitleCss,
  crumbBtnCss,
  crumbsCss,
  entryBtnCss,
  hiddenToggleCss,
  listCss,
  listNoteCss,
  navErrorCss,
  pathInputCss,
  pathRowCss,
  selectionCss,
  shortcutBtnCss,
  sidebarCss,
  smallBtnCss,
} from "../css/FolderBrowserDialog";

interface Props {
  /** Called with the chosen folder (absolute, forward slashes). */
  onSelect: (path: string) => void;
  onCancel: () => void;
  /** The listing could not even start (e.g. no home folder on the server). */
  onFatal: (message: string) => void;
}

// In-page folder picker over the server's filesystem, used when the UI is not
// inside the desktop app (see utils/folderPickerMode.ts). Always opens at the
// server user's home folder.
export default function FolderBrowserDialog({
  onSelect,
  onCancel,
  onFatal,
}: Props) {
  const browser = useFolderBrowser(onFatal);
  const { listing, selection } = browser;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      css={browserBackdropCss}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div css={browserDialogCss}>
        <div css={browserHeaderCss}>
          <div css={browserTitleCss}>Select Working Directory</div>
          <div css={pathRowCss}>
            <button
              css={smallBtnCss}
              disabled={!listing?.parent_path}
              onClick={() =>
                listing?.parent_path && browser.navigate(listing.parent_path)
              }
              title="Up one folder"
            >
              ↑
            </button>
            <input
              css={pathInputCss(browser.navError !== null)}
              type="text"
              value={browser.pathDraft}
              onChange={(e) => browser.editPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  browser.submitPath();
                } else if (e.key === "Escape") {
                  // Only undo the edit; don't also close the picker.
                  e.stopPropagation();
                  e.nativeEvent.stopImmediatePropagation();
                  browser.resetPath();
                }
              }}
              onBlur={() => {
                if (browser.navError === null) browser.resetPath();
              }}
              placeholder="Type a path and press Enter (~ = home)"
              spellCheck={false}
            />
          </div>
          {browser.navError && <div css={navErrorCss}>{browser.navError}</div>}
          {listing && (
            <div css={crumbsCss}>
              {breadcrumbs(listing.path).map((crumb) => (
                <button
                  key={crumb.path}
                  css={crumbBtnCss}
                  onClick={() => browser.navigate(crumb.path)}
                >
                  {crumb.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div css={browserBodyCss}>
          <div css={sidebarCss}>
            {listing?.shortcuts.map((shortcut) => (
              <button
                key={shortcut.path}
                css={shortcutBtnCss(shortcut.path === listing.path)}
                onClick={() => browser.navigate(shortcut.path)}
                title={shortcut.path}
              >
                {shortcut.label}
              </button>
            ))}
          </div>
          <div css={listCss}>
            {listing === null ? (
              <div css={listNoteCss}>Loading…</div>
            ) : listing.entries.length === 0 ? (
              <div css={listNoteCss}>No sub-folders.</div>
            ) : (
              listing.entries.map((entry) => (
                <button
                  key={entry.path}
                  css={entryBtnCss(browser.selected === entry.path)}
                  onClick={() =>
                    browser.setSelected(
                      browser.selected === entry.path ? null : entry.path,
                    )
                  }
                  onDoubleClick={() => browser.navigate(entry.path)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      browser.navigate(entry.path);
                    }
                  }}
                  title={entry.path}
                >
                  📁 {entry.name}
                </button>
              ))
            )}
            {listing?.truncated && (
              <div css={listNoteCss}>
                Showing the first {listing.entries.length} folders. Type a path
                above to reach others.
              </div>
            )}
          </div>
        </div>

        <div css={browserFooterCss}>
          <label css={hiddenToggleCss}>
            <input
              type="checkbox"
              checked={browser.showHidden}
              onChange={browser.toggleHidden}
            />
            Show hidden
          </label>
          <div css={selectionCss} title={selection ?? undefined}>
            <bdi dir="ltr">{selection ?? ""}</bdi>
          </div>
          <button css={cancelBtnCss} onClick={onCancel}>
            Cancel
          </button>
          <button
            css={createBtnCss(selection === null || browser.loading)}
            disabled={selection === null || browser.loading}
            onClick={() => selection && onSelect(selection)}
          >
            Select
          </button>
        </div>
      </div>
    </div>
  );
}
