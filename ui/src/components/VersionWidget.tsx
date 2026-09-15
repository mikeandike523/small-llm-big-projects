/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useState } from "react";
import { fetchBackendVersion } from "../api/version";

// Version widget for the dashboard header. The UI version comes from the
// build-time constant __APP_VERSION__ (inlined from ui/package.json by
// vite.config.ts), so it renders instantly. The backend version is fetched
// live from GET /api/version and appears once loaded ("—" on failure).

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

export default function VersionWidget() {
  // Bundled at build time — no loading state needed.
  const uiVersion = __APP_VERSION__;
  const [backendVersion, setBackendVersion] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchBackendVersion().then((v) => {
      if (alive) setBackendVersion(v.version);
    });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div css={widgetCss} title="Application version information">
      <div>
        UI: <span css={valueCss}>{uiVersion}</span>
      </div>
      <div>
        Backend:{" "}
        <span css={valueCss}>{backendVersion ?? "…"}</span>
      </div>
    </div>
  );
}
