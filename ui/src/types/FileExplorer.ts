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
