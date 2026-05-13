import { placeholderCss, dirtySectionLabelCss, dirtyItemCss } from "../../css/DebugPanel";

export default function DirtyTab({ files, memKeys }: { files: string[]; memKeys: string[] }) {
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