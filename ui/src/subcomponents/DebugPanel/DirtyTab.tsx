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

export default function DirtyTab({
  files,
  memKeys,
}: {
  files: string[];
  memKeys: string[];
}) {
  const empty = files.length === 0 && memKeys.length === 0;
  return (
    <>
      {empty && <div css={placeholderCss}>No dirty resources.</div>}
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
      {memKeys.length > 0 && (
        <>
          <div css={dirtySectionLabelCss}>Dirty session memory keys</div>
          {memKeys.map((k) => (
            <div key={k} css={dirtyItemCss}>
              {k}
            </div>
          ))}
        </>
      )}
    </>
  );
}
