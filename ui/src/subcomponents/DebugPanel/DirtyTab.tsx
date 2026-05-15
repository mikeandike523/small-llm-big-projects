import { css } from "@emotion/react";
import { placeholderCss } from "../../css/DebugPanel";

export const dirtySectionLabelCss = css`
  font-family: "Consolas", monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #555;
  margin-bottom: 4px;
  margin-top: 8px;
  &:first-of-type {
    margin-top: 0;
  }
`;

export const dirtyItemCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #c07828;
  word-break: break-all;
  padding: 2px 4px;
`;

export const seenItemCss = css`
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #5a8a6a;
  word-break: break-all;
  padding: 2px 4px;
`;

export default function DirtyTab({
  files,
  seenFiles,
  memKeys,
  seenMemKeys,
}: {
  files: string[];
  seenFiles: string[];
  memKeys: string[];
  seenMemKeys: string[];
}) {
  const empty =
    files.length === 0 &&
    seenFiles.length === 0 &&
    memKeys.length === 0 &&
    seenMemKeys.length === 0;

  return (
    <>
      {empty && <div css={placeholderCss}>No tracked resources.</div>}
      {files.length > 0 && (
        <>
          <div css={dirtySectionLabelCss}>Dirty files</div>
          {files.map((f) => (
            <div key={f} css={dirtyItemCss}>
              {f}
            </div>
          ))}
        </>
      )}
      {seenFiles.length > 0 && (
        <>
          <div css={dirtySectionLabelCss}>Seen files (clean)</div>
          {seenFiles.map((f) => (
            <div key={f} css={seenItemCss}>
              {f}
            </div>
          ))}
        </>
      )}
      {memKeys.length > 0 && (
        <>
          <div css={dirtySectionLabelCss}>Dirty memory keys</div>
          {memKeys.map((k) => (
            <div key={k} css={dirtyItemCss}>
              {k}
            </div>
          ))}
        </>
      )}
      {seenMemKeys.length > 0 && (
        <>
          <div css={dirtySectionLabelCss}>Seen memory keys (clean)</div>
          {seenMemKeys.map((k) => (
            <div key={k} css={seenItemCss}>
              {k}
            </div>
          ))}
        </>
      )}
    </>
  );
}
