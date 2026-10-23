/** @jsxImportSource @emotion/react */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  ExplorerDownloadRequest,
  ExplorerEntryActions,
  ExplorerRenameResult,
  ExplorerRevealRequest,
  FileExplorerListing,
} from "../types/FileExplorer";
import { isPathWithin, retargetPath } from "../utils/explorerPaths";
import ConfirmDialog from "./ConfirmDialog";

interface Props {
  active: boolean;
  initialCwd: string;
  sessionId: string;
  editorOpen: boolean;
  onToggleEditor: () => void;
  onOpenFile: (request: EditorOpenRequest) => void;
  onDownload: (request: ExplorerDownloadRequest) => void;
  onRename: (
    entry: ExplorerDownloadRequest,
    newName: string,
  ) => Promise<ExplorerRenameResult>;
  onDelete: (entry: ExplorerDownloadRequest) => Promise<void>;
  onEntryRenamed: (oldPath: string, newPath: string) => void;
  onEntryDeleting: (path: string) => void;
  revealRequest: ExplorerRevealRequest | null;
}

interface PendingDeleteConfirm {
  entry: ExplorerDownloadRequest;
  resolve: (confirmed: boolean) => void;
}

export default function FileExplorer({
  active,
  initialCwd,
  sessionId,
  editorOpen,
  onToggleEditor,
  onOpenFile,
  onDownload,
  onRename,
  onDelete,
  onEntryRenamed,
  onEntryDeleting,
  revealRequest,
}: Props) {
  const [rootPath, setRootPath] = useState(initialCwd);
  const [homePath, setHomePath] = useState("");
  const [focusedPath, setFocusedPath] = useState<string | null>(null);
  const onRootLoaded = useCallback((listing: FileExplorerListing) => {
    setRootPath(listing.root_path);
    setHomePath(listing.home_path);
  }, []);

  useEffect(() => {
    if (revealRequest) setFocusedPath(revealRequest.path);
  }, [revealRequest]);

  const [deleteConfirm, setDeleteConfirm] =
    useState<PendingDeleteConfirm | null>(null);
  const closeDeleteConfirm = useCallback(
    (confirmed: boolean) => {
      deleteConfirm?.resolve(confirmed);
      setDeleteConfirm(null);
    },
    [deleteConfirm],
  );

  // Rows keep a stable `actions` object; the latest callbacks live in a ref.
  const callbacks = useRef({
    onDownload,
    onRename,
    onDelete,
    onEntryRenamed,
    onEntryDeleting,
  });
  callbacks.current = {
    onDownload,
    onRename,
    onDelete,
    onEntryRenamed,
    onEntryDeleting,
  };
  const actions = useMemo<ExplorerEntryActions>(
    () => ({
      download: (entry) => callbacks.current.onDownload(entry),
      rename: (entry, newName) => callbacks.current.onRename(entry, newName),
      remove: (entry) => callbacks.current.onDelete(entry),
      confirmDelete: (entry) =>
        new Promise<boolean>((resolve) => setDeleteConfirm({ entry, resolve })),
      entryRenamed: (oldPath, newPath) => {
        setFocusedPath((current) =>
          current ? (retargetPath(current, oldPath, newPath) ?? current) : null,
        );
        callbacks.current.onEntryRenamed(oldPath, newPath);
      },
      entryDeleting: (path) => {
        setFocusedPath((current) =>
          current && isPathWithin(current, path) ? null : current,
        );
        callbacks.current.onEntryDeleting(path);
      },
    }),
    [],
  );

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
              path={rootPath || initialCwd}
              onRootLoaded={onRootLoaded}
              focusedPath={focusedPath}
              revealRequest={revealRequest}
              actions={actions}
              onOpenFile={(request) => {
                setFocusedPath(request.path);
                onOpenFile(request);
              }}
            />
          ) : (
            <div>Loading session working directory…</div>
          )}
        </div>
      </div>
      {deleteConfirm && (
        <ConfirmDialog
          title="Delete permanently?"
          confirmLabel="Delete permanently"
          onConfirm={() => closeDeleteConfirm(true)}
          onCancel={() => closeDeleteConfirm(false)}
        >
          Permanently delete{" "}
          {deleteConfirm.entry.kind === "directory" ? "folder" : "file"}{" "}
          <strong style={{ color: "#ccc" }}>{deleteConfirm.entry.name}</strong>
          {deleteConfirm.entry.kind === "directory" &&
            " and everything inside it"}
          ? This cannot be undone.
        </ConfirmDialog>
      )}
    </div>
  );
}
