/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useState } from "react";
import { fetchBackendVersion } from "../api/version";
import { useLatestUiReleaseNote } from "../api/releaseNotes";

// Version widget for the dashboard header. The UI version comes from the
// build-time constant __APP_VERSION__ (inlined from ui/package.json by
// vite.config.ts), so it renders instantly. The backend version is fetched
// live from GET /api/version and appears once loaded ("…" on failure).
// Tooltips include the latest release note for each side (if any); the UI
// line shows a small "•" marker until the note has been seen.

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

const markerCss = css`
  color: #7fb2ff;
  margin-left: 3px;
  font-size: 12px;
  line-height: 1;
`;

const LAST_SEEN_KEY = "slbp-last-seen-ui-release";

export default function VersionWidget() {
  // Bundled at build time — no loading state needed.
  const uiVersion = __APP_VERSION__;
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [backendNote, setBackendNote] = useState<string>("");
  const uiNote = useLatestUiReleaseNote();
  const [seen, setSeen] = useState<boolean>(() =>
    typeof localStorage !== "undefined"
      ? localStorage.getItem(LAST_SEEN_KEY) === uiNote?.version
      : true,
  );

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

  // Mark the UI note as seen when it becomes visible (hover/tooltip).
  useEffect(() => {
    if (uiNote && !seen) {
      localStorage.setItem(LAST_SEEN_KEY, uiNote.version);
      setSeen(true);
    }
  }, [uiNote, seen]);

  const titleParts: string[] = [];
  if (uiNote) titleParts.push(`UI ${uiNote.version}: ${uiNote.message}`);
  if (backendNote) titleParts.push(`Backend: ${backendNote}`);
  const title = titleParts.length ? titleParts.join("\n") : "Application version information";

  return (
    <div css={widgetCss} title={title}>
      <div>
        UI:{" "}
        <span css={valueCss}>
          {uiVersion}
          {uiNote && <span css={markerCss}>•</span>}
        </span>
      </div>
      <div>
        Backend:{" "}
        <span css={valueCss}>{backendVersion ?? "…"}</span>
      </div>
    </div>
  );
}
