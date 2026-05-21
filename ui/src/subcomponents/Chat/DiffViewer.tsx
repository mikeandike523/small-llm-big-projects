import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { css } from "@emotion/react";

const wrapperCss = css`
  font-size: 11px;
  font-family: "Consolas", monospace;
  border-radius: 4px;
  border: 1px solid #2a2a2a;
  max-height: 400px;
  overflow-x: auto;
  overflow-y: auto;
`;

const darkStyles = {
  variables: {
    dark: {
      diffViewerBackground: "#0d0d0d",
      diffViewerColor: "#c8c8c8",
      addedBackground: "#0a1e0a",
      addedColor: "#4ade80",
      removedBackground: "#1e0a0a",
      removedColor: "#f87171",
      wordAddedBackground: "#1a3a1a",
      wordRemovedBackground: "#3a1a1a",
      addedGutterBackground: "#0a1a0a",
      removedGutterBackground: "#1a0a0a",
      gutterBackground: "#111111",
      gutterBackgroundDark: "#0d0d0d",
      gutterColor: "#555555",
      codeFoldBackground: "#111111",
      codeFoldGutterBackground: "#0d0d0d",
      codeFoldContentColor: "#555555",
      emptyLineBackground: "#0d0d0d",
    },
  },
};

export default function DiffViewer({
  before,
  after,
}: {
  before: string;
  after: string;
}) {
  return (
    <div css={wrapperCss}>
      <ReactDiffViewer
        oldValue={before}
        newValue={after}
        splitView={false}
        useDarkTheme={true}
        compareMethod={DiffMethod.LINES}
        showDiffOnly={true}
        extraLinesSurroundingDiff={3}
        hideLineNumbers={false}
        styles={darkStyles}
        disableWorker={true}
      />
    </div>
  );
}
