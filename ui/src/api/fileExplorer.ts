import type { FileExplorerListing } from "../types/FileExplorer";

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
