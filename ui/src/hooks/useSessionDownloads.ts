import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  createExplorerDownload,
  FileExplorerApiError,
  getExplorerDownload,
  startBrowserDownload,
} from "../api/fileExplorer";
import type { BackendLogContent } from "../types/DebugPanel";
import type {
  ExplorerDownloadJob,
  ExplorerDownloadRequest,
} from "../types/FileExplorer";

export type FolderDownloadCardState = ExplorerDownloadJob["state"] | "starting";

export interface FolderDownloadCard {
  id: string;
  downloadName: string;
  state: FolderDownloadCardState;
  fileCount: number;
  filesProcessed: number;
  totalInputBytes: number;
  processedBytes: number;
  error: string | null;
}

const POLL_INTERVAL_MS = 500;
const SUCCESS_CARD_LINGER_MS = 2500;
const ERROR_CARD_LINGER_MS = 12000;

function cardFromJob(job: ExplorerDownloadJob): FolderDownloadCard {
  return {
    id: job.download_id,
    downloadName: job.download_name,
    state: job.state,
    fileCount: job.file_count,
    filesProcessed: job.files_processed,
    totalInputBytes: job.total_input_bytes,
    processedBytes: job.processed_bytes,
    error: job.error,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown download error";
}

export default function useSessionDownloads(
  sessionId: string,
  appendClientDebugLog: (content: BackendLogContent) => void,
) {
  const [folderCards, setFolderCards] = useState<FolderDownloadCard[]>([]);
  const mounted = useRef(true);
  const timers = useRef(new Set<number>());

  const removeCardLater = useCallback((id: string, delay: number) => {
    const timer = window.setTimeout(() => {
      timers.current.delete(timer);
      if (mounted.current) {
        setFolderCards((current) => current.filter((card) => card.id !== id));
      }
    }, delay);
    timers.current.add(timer);
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const timer of timers.current) window.clearTimeout(timer);
      timers.current.clear();
    };
  }, []);

  const failFolderCard = useCallback(
    (id: string, downloadName: string, error: unknown) => {
      const message = errorMessage(error);
      setFolderCards((current) => {
        const failed: FolderDownloadCard = {
          id,
          downloadName,
          state: "failed",
          fileCount: 0,
          filesProcessed: 0,
          totalInputBytes: 0,
          processedBytes: 0,
          error: message,
        };
        const existing = current.some((card) => card.id === id);
        return existing
          ? current.map((card) => (card.id === id ? failed : card))
          : [...current, failed];
      });
      removeCardLater(id, ERROR_CARD_LINGER_MS);
    },
    [removeCardLater],
  );

  const pollFolder = useCallback(
    async (initial: ExplorerDownloadJob) => {
      let job = initial;
      while (mounted.current) {
        setFolderCards((current) =>
          current.map((card) =>
            card.id === job.download_id ? cardFromJob(job) : card,
          ),
        );
        if (job.state === "ready") {
          if (!job.content_url) {
            throw new Error("Prepared download did not include a content URL");
          }
          startBrowserDownload(job.content_url);
          removeCardLater(job.download_id, SUCCESS_CARD_LINGER_MS);
          return;
        }
        if (job.state === "failed") {
          removeCardLater(job.download_id, ERROR_CARD_LINGER_MS);
          return;
        }
        await new Promise<void>((resolve) => {
          const timer = window.setTimeout(() => {
            timers.current.delete(timer);
            resolve();
          }, POLL_INTERVAL_MS);
          timers.current.add(timer);
        });
        if (!mounted.current) return;
        job = await getExplorerDownload(job.download_id);
      }
    },
    [removeCardLater],
  );

  const startDownload = useCallback(
    async (request: ExplorerDownloadRequest) => {
      const localId = crypto.randomUUID();
      if (request.kind === "directory") {
        setFolderCards((current) => [
          ...current,
          {
            id: localId,
            downloadName: `${request.name}.zip`,
            state: "starting",
            fileCount: 0,
            filesProcessed: 0,
            totalInputBytes: 0,
            processedBytes: 0,
            error: null,
          },
        ]);
      }

      try {
        const job = await createExplorerDownload(sessionId, request.path);
        if (request.kind === "file") {
          if (!job.content_url) {
            throw new Error("File download did not include a content URL");
          }
          startBrowserDownload(job.content_url);
          return;
        }
        setFolderCards((current) => [
          ...current.filter((card) => card.id !== localId),
          cardFromJob(job),
        ]);
        void pollFolder(job).catch((error: unknown) => {
          if (!mounted.current) return;
          if (
            !(error instanceof FileExplorerApiError) ||
            !error.backendLogged
          ) {
            appendClientDebugLog({
              source: "file-download",
              path: request.path,
              error: errorMessage(error),
            });
          }
          failFolderCard(job.download_id, job.download_name, error);
        });
      } catch (error) {
        if (!(error instanceof FileExplorerApiError) || !error.backendLogged) {
          appendClientDebugLog({
            source: "file-download",
            path: request.path,
            error: errorMessage(error),
          });
        }
        if (request.kind === "file") {
          toast.error("Failed to download file. Check Debug Panel logs.");
        } else {
          failFolderCard(localId, `${request.name}.zip`, error);
        }
      }
    },
    [appendClientDebugLog, failFolderCard, pollFolder, sessionId],
  );

  return { folderCards, startDownload };
}
