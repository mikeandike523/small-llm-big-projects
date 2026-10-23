/** @jsxImportSource @emotion/react */
import { useCallback, useEffect, useRef, useState } from "react";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";
import { VscFolder, VscFolderOpened } from "react-icons/vsc";
import { listExplorerDirectory } from "../../api/fileExplorer";
import {
  chevronCss,
  folderIconCss,
  nodeRowCss,
  pendingDeleteCss,
  rootHomeCss,
  rootPathCss,
  statusRowCss,
} from "../../css/FileExplorer";
import type {
  FileExplorerEntry,
  FileExplorerListing,
  EditorOpenRequest,
  ExplorerDownloadRequest,
  ExplorerEntryActions,
  ExplorerRevealRequest,
} from "../../types/FileExplorer";
import EntryContextMenu from "./EntryContextMenu";
import EntryRenameInput, { EntryStatusIcon } from "./EntryRenameInput";
import ExplorerFile from "./ExplorerFile";
import useEntryMutations from "./useEntryMutations";
import type { ReloadParent } from "./useEntryMutations";

interface Props {
  active: boolean;
  indent: number;
  name: string;
  path?: string;
  root?: boolean;
  sessionId: string;
  homePath: string;
  onRootLoaded?: (listing: FileExplorerListing) => void;
  onOpenFile: (request: EditorOpenRequest) => void;
  actions: ExplorerEntryActions;
  /** Re-lists the directory containing this one (absent for the root). */
  reloadParent?: ReloadParent;
  /** Bumped by the parent to make loaded descendants re-list themselves. */
  refreshSignal?: number;
  focusedPath: string | null;
  revealRequest: ExplorerRevealRequest | null;
}

const noParent: ReloadParent = async () => null;

function splitHomePrefix(path: string, homePath: string): [string, string] {
  const windowsPath = /^[A-Za-z]:\//.test(path);
  const comparablePath = windowsPath ? path.toLowerCase() : path;
  const comparableHome = windowsPath ? homePath.toLowerCase() : homePath;
  const matches =
    comparablePath === comparableHome ||
    comparablePath.startsWith(`${comparableHome}/`);
  return matches
    ? [path.slice(0, homePath.length), path.slice(homePath.length)]
    : ["", path];
}

export default function ExplorerNode({
  active,
  indent,
  name,
  path,
  root = false,
  sessionId,
  homePath,
  onRootLoaded,
  onOpenFile,
  actions,
  reloadParent = noParent,
  refreshSignal = 0,
  focusedPath,
  revealRequest,
}: Props) {
  const [expanded, setExpanded] = useState(root);
  const [entries, setEntries] = useState<FileExplorerEntry[] | null>(null);
  const [error, setError] = useState("");
  const [childRefreshSignal, setChildRefreshSignal] = useState(0);

  useEffect(() => {
    if (!active || !expanded || entries !== null) return;
    const controller = new AbortController();
    setError("");
    listExplorerDirectory(sessionId, root ? undefined : path, controller.signal)
      .then((listing) => {
        setEntries(listing.entries);
        if (root) onRootLoaded?.(listing);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setError(
          reason instanceof Error ? reason.message : "Could not list directory",
        );
      });
    return () => controller.abort();
  }, [active, entries, expanded, onRootLoaded, path, root, sessionId]);

  // Re-list after a child rename/delete. `cascade` also refreshes loaded
  // subfolders, for a folder delete that may have partially succeeded.
  const reloadEntries = useCallback(
    async (cascade = false) => {
      try {
        const listing = await listExplorerDirectory(
          sessionId,
          root ? undefined : path,
        );
        setEntries(listing.entries);
        setError("");
        if (cascade) setChildRefreshSignal((value) => value + 1);
        return listing.entries;
      } catch (reason) {
        setError(
          reason instanceof Error ? reason.message : "Could not list directory",
        );
        return null;
      }
    },
    [path, root, sessionId],
  );

  const seenRefreshSignal = useRef(refreshSignal);
  useEffect(() => {
    if (refreshSignal === seenRefreshSignal.current) return;
    seenRefreshSignal.current = refreshSignal;
    if (entries !== null) void reloadEntries(true);
  }, [entries, refreshSignal, reloadEntries]);

  const reloadOwnEntries = useCallback(() => reloadEntries(), [reloadEntries]);
  const reloadOwnTree = useCallback(() => {
    if (entries !== null) void reloadEntries(true);
  }, [entries, reloadEntries]);

  const directoryParts = name.split(/[\\/]/).filter(Boolean);
  const directoryName = directoryParts[directoryParts.length - 1] || name;
  const directoryEntry: ExplorerDownloadRequest = {
    name: directoryName,
    path: path ?? "",
    kind: "directory",
  };
  const mutation = useEntryMutations(
    directoryEntry,
    actions,
    reloadParent,
    reloadOwnTree,
  );

  const [homePrefix, pathRemainder] = splitHomePrefix(name, homePath);
  const FolderIcon = expanded ? VscFolderOpened : VscFolder;
  const icons = (
    <>
      <span css={chevronCss}>
        {expanded ? <FiChevronDown size={13} /> : <FiChevronRight size={13} />}
      </span>
      <span css={[folderIconCss, mutation.deleting && pendingDeleteCss]}>
        <FolderIcon size={16} />
      </span>
    </>
  );
  const row = (
    <>
      {icons}
      {root ? (
        <span>
          <span css={rootHomeCss}>{homePrefix}</span>
          <span css={rootPathCss}>{pathRemainder}</span>
        </span>
      ) : (
        <span css={mutation.deleting && pendingDeleteCss}>{name}</span>
      )}
      <EntryStatusIcon status={mutation.status} />
    </>
  );

  let header = null;
  if (root) {
    header = path ? (
      <EntryContextMenu entry={directoryEntry} onDownload={actions.download}>
        <div css={nodeRowCss(indent, false)} title={name}>
          {row}
        </div>
      </EntryContextMenu>
    ) : (
      <div css={nodeRowCss(indent, false)} title={name}>
        {row}
      </div>
    );
  } else if (path && mutation.renaming) {
    header = (
      <div css={nodeRowCss(indent, false)}>
        {icons}
        <EntryRenameInput
          value={mutation.draft}
          kind="directory"
          status={mutation.status}
          onChange={mutation.setDraft}
          onCommit={() => void mutation.commitRename()}
          onCancel={mutation.cancelRename}
        />
      </div>
    );
  } else if (path) {
    header = (
      <EntryContextMenu
        entry={directoryEntry}
        disabled={mutation.deleting}
        onDownload={actions.download}
        onRename={mutation.startRename}
        onDelete={() => void mutation.requestDelete()}
      >
        <button
          type="button"
          css={nodeRowCss(indent, true)}
          disabled={mutation.deleting}
          onClick={() => setExpanded((value) => !value)}
          title={path}
        >
          {row}
        </button>
      </EntryContextMenu>
    );
  }

  return (
    <div role="treeitem" aria-expanded={expanded}>
      {header}
      {expanded && entries === null && !error && (
        <div css={statusRowCss(indent)}>Loading…</div>
      )}
      {expanded && error && <div css={statusRowCss(indent, true)}>{error}</div>}
      {expanded && entries && (
        <div role="group">
          {entries.map((entry) =>
            entry.kind === "directory" ? (
              <ExplorerNode
                key={entry.path}
                active={active}
                indent={indent + 1}
                name={entry.name}
                path={entry.path}
                sessionId={sessionId}
                homePath={homePath}
                onOpenFile={onOpenFile}
                focusedPath={focusedPath}
                revealRequest={revealRequest}
                actions={actions}
                reloadParent={reloadOwnEntries}
                refreshSignal={childRefreshSignal}
              />
            ) : (
              <ExplorerFile
                key={entry.path}
                entry={entry}
                indent={indent + 1}
                onOpenFile={onOpenFile}
                focused={entry.path === focusedPath}
                active={active}
                revealRequest={revealRequest}
                actions={actions}
                reloadParent={reloadOwnEntries}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
