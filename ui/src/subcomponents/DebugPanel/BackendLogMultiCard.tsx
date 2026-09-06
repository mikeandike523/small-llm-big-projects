import { css } from "@emotion/react";
import { BackendLogMultiEntry } from "../../types/DebugPanel";
import { spBorderStrong } from "../../css/SidePanelTheme";
import { BackendLogContentView } from "./BackendLogEntryItem";

const multiCardCss = css`
  border: 1px solid ${spBorderStrong};
  border-radius: 5px;
  padding: 4px;
  margin: 3px 0;
  overflow: hidden;
  background: rgba(9, 22, 34, 0.78);
  box-shadow:
    0 0 0 1px rgba(111, 159, 228, 0.08),
    0 0 9px rgba(111, 159, 228, 0.1);
`;

const multiRowCss = (index: number) => css`
  background: ${
    index % 2 === 0 ? "rgba(18, 39, 58, 0.78)" : "rgba(24, 49, 72, 0.78)"
  };
  &:first-of-type {
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
  }
  &:last-of-type {
    border-bottom-left-radius: 3px;
    border-bottom-right-radius: 3px;
  }
`;

export default function BackendLogMultiCard({
  entry,
  onView,
}: {
  entry: BackendLogMultiEntry;
  onView: (entry: {
    id: number;
    content: Record<string, unknown> | unknown[];
  }) => void;
}) {
  return (
    <div css={multiCardCss}>
      {entry.content.map((content, index) => (
        <div key={`${entry.id}-${index}`} css={multiRowCss(index)}>
          <BackendLogContentView
            id={entry.id}
            content={content}
            onView={onView}
          />
        </div>
      ))}
    </div>
  );
}
