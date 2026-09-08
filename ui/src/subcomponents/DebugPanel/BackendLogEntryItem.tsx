import Ansi from "ansi-to-react";
import { css } from "@emotion/react";
import {
  BackendLogContent,
  BackendLogSingleEntry,
} from "../../types/DebugPanel";
import { fontMono, spTextMain } from "../../css/SidePanelTheme";
import { BACKEND_LOG_OBJECT_TRUNCATE_CHARS } from "../../constants/tool-ui-constants";

export const logLineCss = css`
  border-bottom: 1px solid #1a3f66;
`;

export const logContentCss = css`
  font-family: ${fontMono};
  color: ${spTextMain};
  font-size: 10px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 2px;
`;

const objectRowCss = css`
  ${logContentCss};
  position: relative;
`;

const viewButtonCss = css`
  position: absolute;
  top: 2px;
  right: 2px;
  z-index: 1;
  background: #19283b;
  color: #6b9fe4;
  border: 1px solid #2b4a70;
  border-radius: 3px;
  font-size: 9px;
  font-family: inherit;
  padding: 0 6px;
  cursor: pointer;
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
  &:hover {
    background: #26364d;
  }
`;

function truncateForPreview(text: string): string {
  if (text.length <= BACKEND_LOG_OBJECT_TRUNCATE_CHARS) return text;
  const more = text.length - BACKEND_LOG_OBJECT_TRUNCATE_CHARS;
  return `${text.slice(0, BACKEND_LOG_OBJECT_TRUNCATE_CHARS)}... (${more} more)`;
}

export default function BackendLogEntryItem({
  entry,
  onView,
}: {
  entry: BackendLogSingleEntry;
  onView: (entry: {
    id: number;
    content: Record<string, unknown> | unknown[];
  }) => void;
}) {
  return (
    <div css={logLineCss}>
      <BackendLogContentView
        id={entry.id}
        content={entry.content}
        onView={onView}
      />
    </div>
  );
}

export function BackendLogContentView({
  id,
  content,
  onView,
}: {
  id: number;
  content: BackendLogContent;
  onView: (entry: {
    id: number;
    content: Record<string, unknown> | unknown[];
  }) => void;
}) {
  const isObjectLike = content !== null && typeof content === "object";

  if (!isObjectLike) {
    if (typeof content === "string") {
      return (
        <div css={logContentCss}>
          <Ansi>{content}</Ansi>
        </div>
      );
    }
    // number | boolean | null -- no ANSI parsing needed, no modal to open.
    return <div css={logContentCss}>{String(content)}</div>;
  }

  const preview = truncateForPreview(JSON.stringify(content, null, 2));

  return (
    <div css={objectRowCss}>
      {/* ansi-to-react escapes nothing and leaves plain text untouched,
          so wrapping the JSON preview is safe and colorizes any ANSI
          sequences embedded in object values. */}
      <Ansi>{preview}</Ansi>
      <button
        css={viewButtonCss}
        onClick={() =>
          onView({
            id,
            content: content as Record<string, unknown> | unknown[],
          })
        }
      >
        View
      </button>
    </div>
  );
}
