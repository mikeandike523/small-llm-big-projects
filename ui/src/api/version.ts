// Backend version fetch, served by GET /api/version so the version widget on
// the dashboard can display the currently running server version.
export type BackendVersion = {
  version: string;
};

export function fetchBackendVersion(): Promise<BackendVersion> {
  return fetch("/api/version")
    .then((r) => {
      if (!r.ok) throw new Error(`Server returned ${r.status}`);
      return r.json() as Promise<BackendVersion>;
    })
    .catch((err) => {
      console.error("Failed to load backend version", err);
      return { version: "unknown" };
    });
}
