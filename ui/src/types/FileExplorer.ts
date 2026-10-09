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
