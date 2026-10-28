import { useCallback, useEffect, useRef, useState } from "react";
import { listFolder, type FolderListing } from "../api/folderBrowser";

// State for FolderBrowserDialog.
//
// - `listing` is the last folder that loaded successfully; a failed navigation
//   never replaces it, it only sets `navError` (shown under the path field).
// - `pathDraft` is the editable path field. It follows `listing.path` after
//   every successful load and is otherwise left as typed, so a typo stays
//   visible next to its error.
// - Each load aborts the previous one, so a slow response can never overwrite
//   a newer folder the user already moved to.
// - A failure of the *first* load (e.g. the server has no home folder) is
//   fatal: it goes to `onFatal` and the dialog closes.
export function useFolderBrowser(onFatal: (message: string) => void) {
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [pathDraft, setPathDraft] = useState("");
  const [navError, setNavError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [loading, setLoading] = useState(false);

  const controllerRef = useRef<AbortController | null>(null);
  const listingRef = useRef<FolderListing | null>(null);
  const onFatalRef = useRef(onFatal);
  onFatalRef.current = onFatal;

  const load = useCallback(
    async (path: string | undefined, hidden: boolean) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setLoading(true);
      try {
        const next = await listFolder(path, hidden, controller.signal);
        if (controller.signal.aborted) return;
        listingRef.current = next;
        setListing(next);
        setPathDraft(next.path);
        setSelected(null);
        setNavError(null);
      } catch (e) {
        if (controller.signal.aborted) return;
        const message =
          e instanceof Error ? e.message : "Could not list folder";
        if (listingRef.current === null) onFatalRef.current(message);
        else setNavError(message);
      } finally {
        if (controllerRef.current === controller) setLoading(false);
      }
    },
    [],
  );

  // Always start at home (path omitted).
  useEffect(() => {
    void load(undefined, false);
    return () => controllerRef.current?.abort();
  }, [load]);

  const navigate = useCallback(
    (path: string) => void load(path, showHidden),
    [load, showHidden],
  );

  const toggleHidden = useCallback(() => {
    const next = !showHidden;
    setShowHidden(next);
    void load(listingRef.current?.path, next);
  }, [load, showHidden]);

  const editPath = useCallback((value: string) => {
    setPathDraft(value);
    setNavError(null);
  }, []);

  /** Submit the path field (Enter). Blank or unchanged input just reloads. */
  const submitPath = useCallback(() => {
    const target = pathDraft.trim();
    navigate(target || listingRef.current?.path || "");
  }, [navigate, pathDraft]);

  /** Put the field back to the current folder (Esc, or blur without an error). */
  const resetPath = useCallback(() => {
    if (listingRef.current) setPathDraft(listingRef.current.path);
    setNavError(null);
  }, []);

  return {
    listing,
    pathDraft,
    navError,
    selected,
    setSelected,
    showHidden,
    loading,
    navigate,
    toggleHidden,
    editPath,
    submitPath,
    resetPath,
    /** The folder "Select" would return: the single-clicked entry, else the current folder. */
    selection: selected ?? listing?.path ?? null,
  };
}

/** Clickable path prefixes for the breadcrumb bar, e.g. "/", "/home", "/home/me". */
export function breadcrumbs(path: string): { label: string; path: string }[] {
  const parts = path.split("/").filter((p, i) => p !== "" || i === 0);
  const crumbs: { label: string; path: string }[] = [];
  let acc = "";
  parts.forEach((part, i) => {
    if (i === 0) {
      // "" for POSIX root, "C:" for a Windows drive.
      acc = part === "" ? "/" : `${part}/`;
      crumbs.push({ label: acc, path: acc });
      return;
    }
    acc = acc.endsWith("/") ? `${acc}${part}` : `${acc}/${part}`;
    crumbs.push({ label: part, path: acc });
  });
  return crumbs;
}
