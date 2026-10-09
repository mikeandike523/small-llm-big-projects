/** @jsxImportSource @emotion/react */
import { useCallback, useState } from "react";
import { VscOpenPreview } from "react-icons/vsc";
import {
  explorerHeaderCss,
  explorerHeaderButtonCss,
  explorerHeaderTitleCss,
  explorerPanelCss,
  treeCss,
  treeScrollCss,
} from "../css/FileExplorer";
import ExplorerNode from "../subcomponents/FileExplorer/ExplorerNode";
import type {
  EditorOpenRequest,
  FileExplorerListing,
} from "../types/FileExplorer";

interface Props {
  active: boolean;
  initialCwd: string;
  sessionId: string;
  editorOpen: boolean;
  onToggleEditor: () => void;
  onOpenFile: (request: EditorOpenRequest) => void;
}

export default function FileExplorer({
  active,
  initialCwd,
  sessionId,
  editorOpen,
  onToggleEditor,
  onOpenFile,
}: Props) {
  const [rootPath, setRootPath] = useState(initialCwd);
  const [homePath, setHomePath] = useState("");
  const onRootLoaded = useCallback((listing: FileExplorerListing) => {
    setRootPath(listing.root_path);
    setHomePath(listing.home_path);
  }, []);

  return (
    <div css={explorerPanelCss}>
      <div css={explorerHeaderCss}>
        <span css={explorerHeaderTitleCss}>Explorer</span>
        <button
          type="button"
          css={explorerHeaderButtonCss(editorOpen)}
          onClick={onToggleEditor}
          title={editorOpen ? "Close text editor" : "Open text editor"}
          aria-label={editorOpen ? "Close text editor" : "Open text editor"}
          aria-pressed={editorOpen}
        >
          <VscOpenPreview size={16} />
        </button>
      </div>
      <div css={treeScrollCss}>
        <div css={treeCss} role="tree" aria-label="Session files">
          {initialCwd ? (
            <ExplorerNode
              key={sessionId}
              active={active}
              indent={0}
              name={rootPath || initialCwd}
              root
              sessionId={sessionId}
              homePath={homePath}
              onRootLoaded={onRootLoaded}
              onOpenFile={onOpenFile}
            />
          ) : (
            <div>Loading session working directory…</div>
          )}
        </div>
      </div>
    </div>
  );
}
