import { retargetPath } from "../utils/explorerPaths";
import { readSessionValue } from "../utils/sessionStorage";

export interface EditorTab {
  path: string;
  name: string;
  parentDir: string;
  content: string;
  savedContent: string;
  preview: boolean;
  loading: boolean;
  saving: boolean;
  error: string;
}

export interface StoredWorkspace {
  tabs: Array<{ path: string; preview: boolean }>;
  activePath: string | null;
}

export const fileName = (path: string) => path.split(/[\\/]/).pop() || path;

export function parentDirName(path: string, rootPath: string): string {
  if (!rootPath) return "";
  const normPath = path.replace(/\\/g, "/");
  const normRoot = rootPath.replace(/\\/g, "/");
  const prefix = normRoot.endsWith("/") ? normRoot : `${normRoot}/`;
  if (!normPath.startsWith(prefix)) return "";
  const rel = normPath.slice(prefix.length);
  const slash = rel.lastIndexOf("/");
  return slash >= 0 ? rel.slice(0, slash) : "";
}

export function blankTab(
  path: string,
  preview: boolean,
  parentDir: string,
): EditorTab {
  return {
    path,
    name: fileName(path),
    parentDir,
    content: "",
    savedContent: "",
    preview,
    loading: true,
    saving: false,
    error: "",
  };
}

export function restoredWorkspace(storageKey: string): StoredWorkspace {
  try {
    const value = readSessionValue(storageKey);
    if (!value) return { tabs: [], activePath: null };
    const parsed = JSON.parse(value) as StoredWorkspace;
    if (!Array.isArray(parsed.tabs)) throw new Error("Invalid tabs");
    return {
      tabs: parsed.tabs.filter(
        (tab) => typeof tab.path === "string" && tab.path.length > 0,
      ),
      activePath:
        typeof parsed.activePath === "string" ? parsed.activePath : null,
    };
  } catch {
    return { tabs: [], activePath: null };
  }
}

/** Point tabs at a renamed file/folder, keeping unsaved edits. */
export function retargetTabs(
  tabs: EditorTab[],
  oldPath: string,
  newPath: string,
  rootPath: string,
): EditorTab[] {
  return tabs.map((tab) => {
    const path = retargetPath(tab.path, oldPath, newPath);
    return path
      ? {
          ...tab,
          path,
          name: fileName(path),
          parentDir: parentDirName(path, rootPath),
        }
      : tab;
  });
}
