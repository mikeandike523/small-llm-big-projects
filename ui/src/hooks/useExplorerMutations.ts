import { useCallback } from "react";
import { toast } from "sonner";
import {
  deleteExplorerEntry,
  FileExplorerApiError,
  renameExplorerEntry,
} from "../api/fileExplorer";
import type { BackendLogContent } from "../types/DebugPanel";
import type {
  ExplorerDownloadRequest,
  ExplorerRenameResult,
} from "../types/FileExplorer";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

const kindLabel = (entry: ExplorerDownloadRequest) =>
  entry.kind === "directory" ? "Folder" : "File";

/**
 * Explorer rename/delete requests. Failures are logged to the Debug Panel
 * (by the backend, or here when the server never answered), toasted, and
 * re-thrown so the explorer row can show its failed state.
 */
export default function useExplorerMutations(
  sessionId: string,
  appendClientDebugLog: (content: BackendLogContent) => void,
) {
  const logClientError = useCallback(
    (source: string, error: unknown, content: Record<string, unknown>) => {
      if (error instanceof FileExplorerApiError && error.backendLogged) return;
      appendClientDebugLog({ source, ...content, error: errorMessage(error) });
    },
    [appendClientDebugLog],
  );

  const renameEntry = useCallback(
    async (
      entry: ExplorerDownloadRequest,
      newName: string,
    ): Promise<ExplorerRenameResult> => {
      try {
        return await renameExplorerEntry(sessionId, entry.path, newName);
      } catch (error) {
        logClientError("file-rename", error, {
          path: entry.path,
          new_name: newName,
        });
        toast.error(
          `${kindLabel(entry)} rename failed. Check Debug Panel logs for details.`,
        );
        throw error;
      }
    },
    [logClientError, sessionId],
  );

  const deleteEntry = useCallback(
    async (entry: ExplorerDownloadRequest): Promise<void> => {
      try {
        await deleteExplorerEntry(sessionId, entry.path);
      } catch (error) {
        logClientError("file-delete", error, { path: entry.path });
        toast.error(
          `${kindLabel(entry)} delete failed. Check Debug Panel logs for details.`,
        );
        throw error;
      }
    },
    [logClientError, sessionId],
  );

  return { renameEntry, deleteEntry };
}
