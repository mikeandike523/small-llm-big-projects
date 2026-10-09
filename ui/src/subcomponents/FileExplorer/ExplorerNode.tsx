/** @jsxImportSource @emotion/react */
import { useEffect, useState } from "react";
import { FileIcon, defaultStyles } from "react-file-icon";
import type { DefaultExtensionType } from "react-file-icon";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";
import { VscFolder, VscFolderOpened } from "react-icons/vsc";
import { listExplorerDirectory } from "../../api/fileExplorer";
import {
  chevronCss,
  fileIconCss,
  folderIconCss,
  nodeRowCss,
  rootHomeCss,
  rootPathCss,
  statusRowCss,
} from "../../css/FileExplorer";
import type {
  FileExplorerEntry,
  FileExplorerListing,
  EditorOpenRequest,
} from "../../types/FileExplorer";

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
}

function extensionFor(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1
    ? name.slice(dot + 1).toLowerCase()
    : "";
}

function ExplorerFile({
  entry,
  indent,
  onOpenFile,
}: {
  entry: FileExplorerEntry;
  indent: number;
  onOpenFile: (request: EditorOpenRequest) => void;
}) {
  const extension = extensionFor(entry.name);
  const iconStyle = defaultStyles[extension as DefaultExtensionType] ?? {
    color: "#41566d",
    foldColor: "#607890",
    glyphColor: "#c9def2",
  };
  return (
    <button
      type="button"
      css={nodeRowCss(indent, true)}
      role="treeitem"
      title={entry.path}
      onClick={() =>
        onOpenFile({ path: entry.path, pinned: false, requestId: Date.now() })
      }
      onDoubleClick={() =>
        onOpenFile({ path: entry.path, pinned: true, requestId: Date.now() })
      }
    >
      <span css={chevronCss} />
      <span css={fileIconCss}>
        <FileIcon extension={extension || undefined} {...iconStyle} />
      </span>
      <span>{entry.name}</span>
    </button>
  );
}

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
}: Props) {
  const [expanded, setExpanded] = useState(root);
  const [entries, setEntries] = useState<FileExplorerEntry[] | null>(null);
  const [error, setError] = useState("");

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

  const [homePrefix, pathRemainder] = splitHomePrefix(name, homePath);
  const FolderIcon = expanded ? VscFolderOpened : VscFolder;
  const row = (
    <>
      <span css={chevronCss}>
        {expanded ? <FiChevronDown size={13} /> : <FiChevronRight size={13} />}
      </span>
      <span css={folderIconCss}>
        <FolderIcon size={16} />
      </span>
      {root ? (
        <span>
          <span css={rootHomeCss}>{homePrefix}</span>
          <span css={rootPathCss}>{pathRemainder}</span>
        </span>
      ) : (
        <span>{name}</span>
      )}
    </>
  );

  return (
    <div role="treeitem" aria-expanded={expanded}>
      {root ? (
        <div css={nodeRowCss(indent, false)} title={name}>
          {row}
        </div>
      ) : (
        <button
          type="button"
          css={nodeRowCss(indent, true)}
          onClick={() => setExpanded((value) => !value)}
          title={path}
        >
          {row}
        </button>
      )}
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
              />
            ) : (
              <ExplorerFile
                key={entry.path}
                entry={entry}
                indent={indent + 1}
                onOpenFile={onOpenFile}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
