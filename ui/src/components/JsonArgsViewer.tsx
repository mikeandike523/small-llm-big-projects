import { css } from "@emotion/react";

import scrollbarCss, { thinScrollbarCss } from "../css/scrollBarCss";

const JSON_VALUE_MAX_LINES = 10;

const jsonRowCss = css`
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  margin-bottom: 2px;
`;

const jsonKeyCss = css`
  color: #6b9fe4;
  font-family: "Consolas", monospace;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
`;

const jsonValueCss = css`
  background: #202030;
  color: #b8bfd8;
  font-family: "Consolas", monospace;
  font-size: 11px;
  padding: 0px 5px;
  border-radius: 3px;
  white-space: pre;
  overflow-x: auto;
  flex: 1;
  min-width: 0;
  ${thinScrollbarCss}
`;

const jsonValueScrollableCss = css`
  background: #202030;
  color: #b8bfd8;
  font-family: "Consolas", monospace;
  font-size: 11px;
  padding: 2px 5px;
  border-radius: 3px;
  white-space: pre;
  width: 100%;
  box-sizing: border-box;
  max-height: ${JSON_VALUE_MAX_LINES}em;
  overflow-x: auto;
  overflow-y: auto;
  display: block;
  ${scrollbarCss}
`;

function formatJsonLeaf(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value) ?? "undefined";
}

function JsonEntry({
  name,
  value,
  depth,
}: {
  name: string;
  value: unknown;
  depth: number;
}): React.ReactElement {
  const isNested = value !== null && typeof value === "object";

  if (isNested) {
    const entries: [string, unknown][] = Array.isArray(value)
      ? (value as unknown[]).map((v, i) => [String(i), v])
      : Object.entries(value as Record<string, unknown>);
    return (
      <>
        <div css={jsonRowCss} style={{ paddingLeft: depth * 16 }}>
          <span css={jsonKeyCss}>{name}</span>
        </div>
        {entries.map(([k, v]) => (
          <JsonEntry key={k} name={k} value={v} depth={depth + 1} />
        ))}
      </>
    );
  }

  const text = formatJsonLeaf(value);
  const isMultiline = typeof value === "string" && value.includes("\n");

  return (
    <div css={jsonRowCss} style={{ paddingLeft: depth * 16 }}>
      <span css={jsonKeyCss}>{name}</span>
      <code css={isMultiline ? jsonValueScrollableCss : jsonValueCss}>
        {text}
      </code>
    </div>
  );
}

export default function JsonArgsViewer({
  args,
}: {
  args: Record<string, unknown>;
}) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  return (
    <div>
      {entries.map(([k, v]) => (
        <JsonEntry key={k} name={k} value={v} depth={0} />
      ))}
    </div>
  );
}
