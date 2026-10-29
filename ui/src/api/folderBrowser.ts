// Session-less folder browsing and cwd checks for the New Session dialog
// (src/ui_connector/socket_handler_components/folder_browser_api.py).

export interface FolderShortcut {
  label: string;
  path: string;
}

export interface FolderListing {
  home_path: string;
  path: string;
  parent_path: string | null;
  entries: { name: string; path: string }[];
  truncated: boolean;
  shortcuts: FolderShortcut[];
}

/** Mirrors CwdCheck in src/utils/cwd_policy.py. */
export interface FolderCheck {
  status: "ok" | "warning" | "error";
  resolved_path: string | null;
  message: string | null;
  reason: string | null;
  /** warning only: the folder does not exist yet (its parent does). */
  missing: boolean;
  /** warning only: the folder is privileged / not recommended. */
  privileged: boolean;
}

export class FolderBrowseError extends Error {
  constructor(
    message: string,
    readonly code: string | null,
  ) {
    super(message);
    this.name = "FolderBrowseError";
  }
}

async function postJson<T>(
  route: string,
  body: object,
  failureLabel: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${window.location.origin}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new FolderBrowseError(
      data?.error || `${failureLabel} failed (${response.status})`,
      data?.code ?? null,
    );
  }
  return data as T;
}

export function listFolder(
  path: string | undefined,
  showHidden: boolean,
  signal?: AbortSignal,
): Promise<FolderListing> {
  return postJson(
    "/api/folder-browser/list",
    { path, show_hidden: showHidden },
    "Folder listing",
    signal,
  );
}

export function checkFolder(
  path: string,
  sessionId: string | null,
): Promise<FolderCheck> {
  return postJson(
    "/api/folder-check",
    { path, session_id: sessionId ?? undefined },
    "Folder check",
  );
}
