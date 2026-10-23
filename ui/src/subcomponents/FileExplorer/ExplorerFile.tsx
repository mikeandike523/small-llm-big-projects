/** @jsxImportSource @emotion/react */
import { useEffect, useRef } from "react";
import { FileIcon, defaultStyles } from "react-file-icon";
import type { DefaultExtensionType } from "react-file-icon";
import {
  chevronCss,
  fileIconCss,
  nodeRowCss,
  pendingDeleteCss,
} from "../../css/FileExplorer";
import type {
  EditorOpenRequest,
  ExplorerEntryActions,
  ExplorerRevealRequest,
  FileExplorerEntry,
} from "../../types/FileExplorer";
import EntryContextMenu from "./EntryContextMenu";
import EntryRenameInput, { EntryStatusIcon } from "./EntryRenameInput";
import useEntryMutations from "./useEntryMutations";
import type { ReloadParent } from "./useEntryMutations";

function extensionFor(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1
    ? name.slice(dot + 1).toLowerCase()
    : "";
}

export default function ExplorerFile({
  entry,
  indent,
  onOpenFile,
  focused,
  active,
  revealRequest,
  actions,
  reloadParent,
}: {
  entry: FileExplorerEntry;
  indent: number;
  onOpenFile: (request: EditorOpenRequest) => void;
  focused: boolean;
  active: boolean;
  revealRequest: ExplorerRevealRequest | null;
  actions: ExplorerEntryActions;
  reloadParent: ReloadParent;
}) {
  const mutation = useEntryMutations(entry, actions, reloadParent);
  const rowRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!active || revealRequest?.path !== entry.path) return;
    const animationFrame = window.requestAnimationFrame(() => {
      rowRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
        inline: "center",
      });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [active, entry.path, revealRequest]);

  const extension = extensionFor(entry.name);
  const iconStyle = defaultStyles[extension as DefaultExtensionType] ?? {
    color: "#41566d",
    foldColor: "#607890",
    glyphColor: "#c9def2",
  };
  const icon = (
    <>
      <span css={chevronCss} />
      <span css={[fileIconCss, mutation.deleting && pendingDeleteCss]}>
        <FileIcon extension={extension || undefined} {...iconStyle} />
      </span>
    </>
  );
  if (mutation.renaming) {
    return (
      <div css={nodeRowCss(indent, false, focused)} role="treeitem">
        {icon}
        <EntryRenameInput
          value={mutation.draft}
          kind="file"
          status={mutation.status}
          onChange={mutation.setDraft}
          onCommit={() => void mutation.commitRename()}
          onCancel={mutation.cancelRename}
        />
      </div>
    );
  }
  return (
    <EntryContextMenu
      entry={entry}
      disabled={mutation.deleting}
      onDownload={actions.download}
      onRename={mutation.startRename}
      onDelete={() => void mutation.requestDelete()}
    >
      <button
        type="button"
        ref={rowRef}
        css={nodeRowCss(indent, true, focused)}
        disabled={mutation.deleting}
        role="treeitem"
        aria-current={focused ? "true" : undefined}
        title={entry.path}
        onClick={() =>
          onOpenFile({ path: entry.path, pinned: false, requestId: Date.now() })
        }
        onDoubleClick={() =>
          onOpenFile({ path: entry.path, pinned: true, requestId: Date.now() })
        }
      >
        {icon}
        <span css={mutation.deleting && pendingDeleteCss}>{entry.name}</span>
        <EntryStatusIcon status={mutation.status} />
      </button>
    </EntryContextMenu>
  );
}
