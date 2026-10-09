import type { FileExplorerListing } from "../types/FileExplorer";

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
