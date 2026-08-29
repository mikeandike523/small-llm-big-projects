import { css } from "@emotion/react";

import scrollbarCss, { thinScrollbarCss } from "../css/scrollBarCss";

const JSON_VALUE_MAX_LINES = 10;

// Params that may expand to fill the height set by an adjacent diff viewer column.
// Only tools that show a diff viewer are relevant here.
const EXPANDABLE_PARAMS: Record<string, Set<string>> = {
  text_editor: new Set(["patch"]),
  write_text_file: new Set(["content"]),
};

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
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  max-height: ${JSON_VALUE_MAX_LINES}em;
  overflow-x: auto;
  overflow-y: auto;
  display: block;
  ${scrollbarCss}
`;

// Expandable variant: fills remaining column height instead of capping at a fixed line count.
const jsonValueExpandableCss = css`
  background: #202030;
  color: #b8bfd8;
  font-family: "Consolas", monospace;
  font-size: 11px;
  padding: 2px 5px;
  border-radius: 3px;
  white-space: pre;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  flex: 1;
  min-height: 4em;
  overflow-x: auto;
  overflow-y: auto;
  display: block;
  ${scrollbarCss}
`;

const jsonRowExpandableCss = css`
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 4px;
  margin-bottom: 2px;
`;

const containerTypeIconCss = css`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  align-self: center;
  color: #6e7383;
  opacity: 0.75;
  font-weight: 700;
  font-family: "Consolas", monospace;
  font-size: 11px;
  line-height: 1;
  flex-shrink: 0;
`;

// Pinned to the container's top-left padding edge so it takes no vertical
// space of its own (the container reserves horizontal room via padding-left
// instead of the icon pushing a row into the flow).
const topLevelIconCss = css`
  position: absolute;
  top: 0;
  left: 0;
`;

function ContainerTypeIcon({
  isArray,
  topLevel = false,
}: {
  isArray: boolean;
  topLevel?: boolean;
}) {
  return (
    <span css={[containerTypeIconCss, topLevel && topLevelIconCss]}>
      {isArray ? "[]" : "{}"}
    </span>
  );
}

function formatJsonLeaf(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value) ?? "undefined";
}

function JsonEntry({
  name,
  value,
  depth,
  expandable = false,
}: {
  name: string;
  value: unknown;
  depth: number;
  expandable?: boolean;
}): React.ReactElement {
  const isNested = value !== null && typeof value === "object";

  if (isNested) {
    const entries: [string, unknown][] = Array.isArray(value)
      ? (value as unknown[]).map((v, i) => [String(i), v])
      : Object.entries(value as Record<string, unknown>);
    return (
      <>
        <div css={jsonRowCss} style={{ paddingLeft: depth * 16 }}>
          <ContainerTypeIcon isArray={Array.isArray(value)} />
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

  if (expandable && isMultiline) {
    return (
      <div css={jsonRowExpandableCss} style={{ paddingLeft: depth * 16 }}>
        <span css={jsonKeyCss}>{name}</span>
        <code css={jsonValueExpandableCss}>{text}</code>
      </div>
    );
  }

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
  toolName,
}: {
  args: Record<string, unknown> | unknown[];
  toolName?: string;
}) {
  const isTopArray = Array.isArray(args);
  const entries: [string, unknown][] = isTopArray
    ? (args as unknown[]).map((v, i) => [String(i), v])
    : Object.entries(args as Record<string, unknown>);
  if (entries.length === 0) return null;

  const expandableNames = toolName
    ? (EXPANDABLE_PARAMS[toolName] ?? new Set<string>())
    : new Set<string>();

  // Activate flex-column mode only when an expandable param has multiline content,
  // so height from the adjacent diff column can flow down to the code block.
  const hasExpandableMultiline = entries.some(
    ([k, v]) =>
      expandableNames.has(k) &&
      typeof v === "string" &&
      (v as string).includes("\n")
  );

  if (hasExpandableMultiline) {
    return (
      <div
        style={{
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          flex: 1,
          minHeight: 0,
          position: "relative",
          paddingLeft: 16,
        }}
      >
        <ContainerTypeIcon isArray={isTopArray} topLevel />
        {entries.map(([k, v]) => (
          <JsonEntry
            key={k}
            name={k}
            value={v}
            depth={0}
            expandable={expandableNames.has(k)}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      style={{
        minWidth: 0,
        overflow: "hidden",
        position: "relative",
        paddingLeft: 16,
      }}
    >
      <ContainerTypeIcon isArray={isTopArray} topLevel />
      {entries.map(([k, v]) => (
        <JsonEntry key={k} name={k} value={v} depth={0} />
      ))}
    </div>
  );
}
