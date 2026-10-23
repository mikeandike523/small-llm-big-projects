/** @jsxImportSource @emotion/react */
import type { ReactNode } from "react";
import * as ContextMenu from "@radix-ui/react-context-menu";
import {
  contextMenuContentCss,
  contextMenuDangerItemCss,
  contextMenuItemCss,
  contextMenuSeparatorCss,
} from "../../css/FileExplorer";
import type { ExplorerDownloadRequest } from "../../types/FileExplorer";

/** Right-click menu for an explorer row. Rename/delete are omitted for the root. */
export default function EntryContextMenu({
  entry,
  disabled = false,
  onDownload,
  onRename,
  onDelete,
  children,
}: {
  entry: ExplorerDownloadRequest;
  disabled?: boolean;
  onDownload: (request: ExplorerDownloadRequest) => void;
  onRename?: () => void;
  onDelete?: () => void;
  children: ReactNode;
}) {
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild disabled={disabled}>
        {children}
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content
          css={contextMenuContentCss}
          // Keep focus on the rename input instead of returning it to the row.
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          <ContextMenu.Item
            css={contextMenuItemCss}
            onSelect={() => onDownload(entry)}
          >
            Download
          </ContextMenu.Item>
          {onRename && (
            <ContextMenu.Item css={contextMenuItemCss} onSelect={onRename}>
              Rename
            </ContextMenu.Item>
          )}
          {onDelete && (
            <>
              <ContextMenu.Separator css={contextMenuSeparatorCss} />
              <ContextMenu.Item
                css={contextMenuDangerItemCss}
                onSelect={onDelete}
              >
                Delete permanently
              </ContextMenu.Item>
            </>
          )}
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}
