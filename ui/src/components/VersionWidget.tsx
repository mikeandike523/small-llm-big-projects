/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useState } from "react";
import { fetchBackendVersion } from "../api/version";
import { useLatestUiReleaseNote } from "../api/releaseNotes";
import type { ReleaseSide } from "../api/releaseNotes";
import ChangelogDialog from "./ChangelogDialog";

// Version widget for the dashboard header. The UI version comes from the
// build-time constant __APP_VERSION__ (inlined from ui/package.json by
// vite.config.ts), so it renders instantly. The backend version is fetched
// live from GET /api/version and appears once loaded ("…" on failure).
// Tooltips include the latest release note for each side (if any). Each row
// has its own "Changelogs" button opening the async changelog dialog.

const widgetCss = css`
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  font-size: 10px;
  line-height: 1.3;
  color: #8a9ab8;
  white-space: nowrap;
  user-select: text;
`;

const valueCss = css`
  color: #dbe5ff;
`;

const logsBtnCss = css`
  margin-left: 6px;
  background: none;
  border: 1px solid #2a3754;
  border-radius: 3px;
  color: #8a9ab8;
  font-size: 9px;
  line-height: 1;
  padding: 2px 5px;
  cursor: pointer;
  &:hover {
    color: #dbe5ff;
    border-color: #3d4f74;
  }
`;

export default function VersionWidget() {
  // Bundled at build time — no loading state needed.
  const uiVersion = __APP_VERSION__;
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [backendNote, setBackendNote] = useState<string>("");
  const uiNote = useLatestUiReleaseNote();
  const [dialogSide, setDialogSide] = useState<ReleaseSide | null>(null);

  useEffect(() => {
    let alive = true;
    fetchBackendVersion().then((v) => {
      if (!alive) return;
      setBackendVersion(v.version);
      setBackendNote(v.note ?? "");
    });
    return () => {
      alive = false;
    };
  }, []);

  const titleParts: string[] = [];
  if (uiNote) titleParts.push(`UI ${uiNote.version}: ${uiNote.message}`);
  if (backendNote) titleParts.push(`Backend ${backendVersion}: ${backendNote}`);
  const title = titleParts.length ? titleParts.join("\n") : "Application version information";

  return (
    <div css={widgetCss} title={title}>
      <div>
        UI: <span css={valueCss}>{uiVersion}</span>
        <button css={logsBtnCss} onClick={() => setDialogSide("ui")}>
          Changelogs
        </button>
      </div>
      <div>
        Backend:{" "}
        <span css={valueCss}>{backendVersion ?? "…"}</span>
        <button css={logsBtnCss} onClick={() => setDialogSide("backend")}>
          Changelogs
        </button>
      </div>
      {dialogSide !== null && (
        <ChangelogDialog side={dialogSide} onClose={() => setDialogSide(null)} />
      )}
    </div>
  );
}
