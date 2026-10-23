import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { FAILED_MUTATION_ICON_MS } from "../../constants/file-explorer-behavior";
import type {
  ExplorerDownloadRequest,
  ExplorerEntryActions,
  FileExplorerEntry,
} from "../../types/FileExplorer";

export type MutationStatus = "idle" | "pending" | "failed";

/** Re-lists the parent directory; resolves to its entries, or null on error. */
export type ReloadParent = () => Promise<FileExplorerEntry[] | null>;

/**
 * Rename/delete state for one explorer row. Nothing is rendered
 * optimistically: the row keeps its input (rename) or strike-through (delete)
 * until the server confirms and the parent directory has been re-listed.
 * On failure the row shows a ✕ for FAILED_MUTATION_ICON_MS, then re-lists the
 * parent in case the operation partially succeeded.
 */
export default function useEntryMutations(
  entry: ExplorerDownloadRequest,
  actions: ExplorerEntryActions,
  reloadParent: ReloadParent,
  onDeleteFailedButPresent?: () => void,
) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(entry.name);
  const [renameStatus, setRenameStatus] = useState<MutationStatus>("idle");
  const [deleteStatus, setDeleteStatus] = useState<MutationStatus>("idle");
  const busy = useRef(false);
  const timers = useRef(new Set<number>());

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending) window.clearTimeout(timer);
      pending.clear();
    };
  }, []);

  const afterFailureDelay = useCallback((callback: () => void) => {
    const timer = window.setTimeout(() => {
      timers.current.delete(timer);
      callback();
    }, FAILED_MUTATION_ICON_MS);
    timers.current.add(timer);
  }, []);

  const clearFailureTimers = useCallback(() => {
    for (const timer of timers.current) window.clearTimeout(timer);
    timers.current.clear();
  }, []);

  const startRename = useCallback(() => {
    if (busy.current) return;
    setDraft(entry.name);
    setRenaming(true);
  }, [entry.name]);

  const cancelRename = useCallback(() => {
    if (busy.current) return;
    setRenaming(false);
  }, []);

  const commitRename = useCallback(async () => {
    if (busy.current) return;
    if (draft === entry.name) {
      setRenaming(false);
      return;
    }
    busy.current = true;
    clearFailureTimers();
    setRenameStatus("pending");
    let newPath: string;
    try {
      newPath = (await actions.rename(entry, draft)).path;
    } catch {
      busy.current = false;
      setRenameStatus("failed");
      afterFailureDelay(() => {
        setRenameStatus("idle");
        void reloadParent();
      });
      return;
    }
    actions.entryRenamed(entry.path, newPath);
    await reloadParent();
    // The renamed entry has a new path (React key), so this row normally
    // unmounts with the re-list; reset in case it is still showing.
    busy.current = false;
    setRenameStatus("idle");
    setRenaming(false);
  }, [
    actions,
    afterFailureDelay,
    clearFailureTimers,
    draft,
    entry,
    reloadParent,
  ]);

  const requestDelete = useCallback(async () => {
    if (busy.current) return;
    if (!(await actions.confirmDelete(entry))) return;
    if (busy.current) return;
    busy.current = true;
    clearFailureTimers();
    setRenaming(false);
    setRenameStatus("idle");
    actions.entryDeleting(entry.path);
    setDeleteStatus("pending");
    try {
      await actions.remove(entry);
    } catch {
      busy.current = false;
      setDeleteStatus("failed");
      afterFailureDelay(() => {
        setDeleteStatus("idle");
        void reloadParent().then((entries) => {
          if (!entries) return;
          if (entries.some((candidate) => candidate.path === entry.path)) {
            onDeleteFailedButPresent?.();
          } else {
            toast.warning(
              `"${entry.name}" was deleted, but the server reported an error. Check Debug Panel logs for details.`,
            );
          }
        });
      });
      return;
    }
    await reloadParent();
    busy.current = false;
    setDeleteStatus("idle");
  }, [
    actions,
    afterFailureDelay,
    clearFailureTimers,
    entry,
    onDeleteFailedButPresent,
    reloadParent,
  ]);

  return {
    renaming,
    draft,
    setDraft,
    startRename,
    cancelRename,
    commitRename,
    requestDelete,
    deleting: deleteStatus === "pending",
    /** Status icon to show next to the row/input. */
    status: deleteStatus !== "idle" ? deleteStatus : renameStatus,
    renamePending: renameStatus === "pending",
  };
}
