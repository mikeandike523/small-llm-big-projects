export interface FileExplorerEntry {
  name: string;
  path: string;
  kind: "directory" | "file";
}

export interface FileExplorerListing {
  root_path: string;
  home_path: string;
  path: string;
  entries: FileExplorerEntry[];
}

export interface EditorOpenRequest {
  path: string;
  pinned: boolean;
  requestId: number;
}

export interface ExplorerRevealRequest {
  path: string;
  requestId: number;
}

export interface ExplorerDownloadRequest {
  name: string;
  path: string;
  kind: "directory" | "file";
}

export interface ExplorerRenameResult {
  old_path: string;
  path: string;
  name: string;
  kind: "directory" | "file";
}

export type ExplorerDownloadState =
  | "discovering"
  | "zipping"
  | "ready"
  | "complete"
  | "failed";

export interface ExplorerDownloadJob {
  download_id: string;
  kind: "directory" | "file";
  download_name: string;
  state: ExplorerDownloadState;
  file_count: number;
  files_processed: number;
  total_input_bytes: number;
  processed_bytes: number;
  archive_bytes: number | null;
  error: string | null;
  content_url?: string;
}

/** Explorer rename/delete, forwarded to the editor so its tabs follow along. */
export type ExplorerPathChange =
  | { kind: "renamed"; oldPath: string; newPath: string; requestId: number }
  | { kind: "deleted"; path: string; requestId: number };

/** Everything an explorer row can do to its entry, bundled for prop drilling. */
export interface ExplorerEntryActions {
  download: (entry: ExplorerDownloadRequest) => void;
  /** Rejects (after logging + toasting) when the rename fails. */
  rename: (
    entry: ExplorerDownloadRequest,
    newName: string,
  ) => Promise<ExplorerRenameResult>;
  /** Rejects (after logging + toasting) when the delete fails. */
  remove: (entry: ExplorerDownloadRequest) => Promise<void>;
  confirmDelete: (entry: ExplorerDownloadRequest) => Promise<boolean>;
  entryRenamed: (oldPath: string, newPath: string) => void;
  entryDeleting: (path: string) => void;
}
