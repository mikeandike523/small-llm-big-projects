import { useEffect, useState } from "react";

// Describes one tool/action combination that renders a before/after diff-preview
// widget in its approval bubble. Served by GET /api/tool-preview/config so the
// front-end keeps no hard-coded list in sync with the backend tools.
export type PreviewDescriptor = {
  tool_name: string;
  // Action names that trigger the widget, or null for "every invocation of this
  // tool" (tools with no sub-action, e.g. write_text_file).
  actions: string[] | null;
  // POST route that computes the before/after preview.
  endpoint: string;
  // Which arg holds the path shown in the "Preview for: File(...)" label.
  label_arg: string;
};

// Memoized so the config is fetched exactly once per page load, regardless of
// how many approval bubbles mount.
let cache: Promise<PreviewDescriptor[]> | null = null;

export function fetchToolPreviewConfig(): Promise<PreviewDescriptor[]> {
  if (!cache) {
    cache = fetch(`${window.location.origin}/api/tool-preview/config`)
      .then((r) => r.json())
      .then((data) => (data?.previews as PreviewDescriptor[]) ?? [])
      .catch((err) => {
        // Drop the cache so a later mount can retry; surface an empty list so no
        // preview is shown rather than crashing the approval bubble.
        cache = null;
        console.error("Failed to load tool-preview config", err);
        return [];
      });
  }
  return cache;
}

// Hook returning the loaded descriptors, or null while the (cached) fetch is in
// flight. Re-renders once the config resolves.
export function useToolPreviewConfig(): PreviewDescriptor[] | null {
  const [config, setConfig] = useState<PreviewDescriptor[] | null>(null);
  useEffect(() => {
    let alive = true;
    fetchToolPreviewConfig().then((c) => {
      if (alive) setConfig(c);
    });
    return () => {
      alive = false;
    };
  }, []);
  return config;
}
