/** @jsxImportSource @emotion/react */
import { useCallback, useState } from "react";
import {
  explorerHeaderCss,
  explorerPanelCss,
  treeCss,
  treeScrollCss,
} from "../css/FileExplorer";
import ExplorerNode from "../subcomponents/FileExplorer/ExplorerNode";
import type { FileExplorerListing } from "../types/FileExplorer";

interface Props {
  active: boolean;
  initialCwd: string;
  sessionId: string;
}

export default function FileExplorer({ active, initialCwd, sessionId }: Props) {
  const [rootPath, setRootPath] = useState(initialCwd);
  const [homePath, setHomePath] = useState("");
  const onRootLoaded = useCallback((listing: FileExplorerListing) => {
    setRootPath(listing.root_path);
    setHomePath(listing.home_path);
  }, []);

  return (
    <div css={explorerPanelCss}>
      <div css={explorerHeaderCss}>Explorer</div>
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
            />
          ) : (
            <div>Loading session working directory…</div>
          )}
        </div>
      </div>
    </div>
  );
}
