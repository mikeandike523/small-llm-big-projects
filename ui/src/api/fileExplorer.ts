import type {
  ExplorerDownloadJob,
  ExplorerRenameResult,
  FileExplorerListing,
} from "../types/FileExplorer";

export class FileExplorerApiError extends Error {
  constructor(
    message: string,
    readonly backendLogged: boolean,
  ) {
    super(message);
    this.name = "FileExplorerApiError";
  }
}

async function postFileExplorer<T>(route: string, body: object): Promise<T> {
  const response = await fetch(`${window.location.origin}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error || `File request failed (${response.status})`);
  }
  return data as T;
}

export async function listExplorerDirectory(
  sessionId: string,
  path?: string,
  signal?: AbortSignal,
): Promise<FileExplorerListing> {
  const response = await fetch(
    `${window.location.origin}/api/file-explorer/list`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, path }),
      signal,
    },
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(
      data?.error || `Directory listing failed (${response.status})`,
    );
  }
  return data as FileExplorerListing;
}

export async function readExplorerFile(
  sessionId: string,
  path: string,
): Promise<{ path: string; content: string }> {
  return postFileExplorer("/api/file-explorer/read", {
    session_id: sessionId,
    path,
  });
}

export async function writeExplorerFile(
  sessionId: string,
  path: string,
  content: string,
): Promise<void> {
  await postFileExplorer("/api/file-explorer/write", {
    session_id: sessionId,
    path,
    content,
  });
}

async function explorerApiRequest<T>(
  url: string,
  init: RequestInit | undefined,
  backendErrorsLogged: boolean,
  failureLabel: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw new FileExplorerApiError(
      error instanceof Error ? error.message : "Could not reach the server",
      false,
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new FileExplorerApiError(
      data?.error || `${failureLabel} failed (${response.status})`,
      backendErrorsLogged,
    );
  }
  return data as T;
}

function downloadJobRequest(
  url: string,
  init?: RequestInit,
  backendErrorsLogged = false,
): Promise<ExplorerDownloadJob> {
  return explorerApiRequest(url, init, backendErrorsLogged, "Download request");
}

function postLoggedExplorerMutation<T>(
  route: string,
  body: object,
  failureLabel: string,
): Promise<T> {
  return explorerApiRequest(
    `${window.location.origin}${route}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    true,
    failureLabel,
  );
}

export function renameExplorerEntry(
  sessionId: string,
  path: string,
  newName: string,
): Promise<ExplorerRenameResult> {
  return postLoggedExplorerMutation(
    "/api/file-explorer/rename",
    { session_id: sessionId, path, new_name: newName },
    "Rename",
  );
}

export async function deleteExplorerEntry(
  sessionId: string,
  path: string,
): Promise<void> {
  await postLoggedExplorerMutation(
    "/api/file-explorer/delete",
    { session_id: sessionId, path },
    "Delete",
  );
}

export function createExplorerDownload(
  sessionId: string,
  path: string,
): Promise<ExplorerDownloadJob> {
  return downloadJobRequest(
    `${window.location.origin}/api/file-explorer/downloads`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, path }),
    },
    true,
  );
}

export function getExplorerDownload(
  downloadId: string,
): Promise<ExplorerDownloadJob> {
  return downloadJobRequest(
    `${window.location.origin}/api/file-explorer/downloads/${encodeURIComponent(downloadId)}`,
  );
}

export function startBrowserDownload(contentUrl: string): void {
  const link = document.createElement("a");
  link.href = new URL(contentUrl, window.location.origin).toString();
  link.download = "";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
