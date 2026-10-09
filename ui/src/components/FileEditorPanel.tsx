/** @jsxImportSource @emotion/react */
import Editor from "@monaco-editor/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { VscClose, VscSave } from "react-icons/vsc";
import { readExplorerFile, writeExplorerFile } from "../api/fileExplorer";
import {
  dirtyMarkerCss,
  editorActionCss,
  editorBodyCss,
  editorEmptyCss,
  editorErrorCss,
  editorOverlayCss,
  editorStatusCss,
  editorTabCss,
  editorTabNameCss,
  editorTabsCss,
  editorTopBarCss,
  statusAccentCss,
  statusPathCss,
  tabCloseCss,
} from "../css/FileEditorPanel";
import type { EditorOpenRequest } from "../types/FileExplorer";
import { readSessionValue, writeSessionValue } from "../utils/sessionStorage";

interface EditorTab {
  path: string;
  name: string;
  content: string;
  savedContent: string;
  preview: boolean;
  loading: boolean;
  saving: boolean;
  error: string;
}

interface Props {
  open: boolean;
  sessionId: string;
  request: EditorOpenRequest | null;
  onClose: () => void;
}

interface StoredWorkspace {
  tabs: Array<{ path: string; preview: boolean }>;
  activePath: string | null;
}

const fileName = (path: string) => path.split(/[\\/]/).pop() || path;

function blankTab(path: string, preview: boolean): EditorTab {
  return {
    path,
    name: fileName(path),
    content: "",
    savedContent: "",
    preview,
    loading: true,
    saving: false,
    error: "",
  };
}

function languageFor(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase();
  const languages: Record<string, string> = {
    c: "c",
    cc: "cpp",
    cpp: "cpp",
    cs: "csharp",
    css: "css",
    go: "go",
    html: "html",
    java: "java",
    js: "javascript",
    json: "json",
    jsx: "javascript",
    md: "markdown",
    py: "python",
    rs: "rust",
    sh: "shell",
    sql: "sql",
    ts: "typescript",
    tsx: "typescript",
    xml: "xml",
    yaml: "yaml",
    yml: "yaml",
  };
  return languages[extension ?? ""] ?? "plaintext";
}

function restoredWorkspace(storageKey: string): StoredWorkspace {
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

export default function FileEditorPanel({
  open,
  sessionId,
  request,
  onClose,
}: Props) {
  const storageKey = `slbp:file-editor:${sessionId}`;
  const restored = useMemo(() => restoredWorkspace(storageKey), [storageKey]);
  const [tabs, setTabs] = useState<EditorTab[]>(() =>
    restored.tabs.map((tab) => blankTab(tab.path, tab.preview)),
  );
  const [activePath, setActivePath] = useState<string | null>(() =>
    restored.tabs.some((tab) => tab.path === restored.activePath)
      ? restored.activePath
      : (restored.tabs[0]?.path ?? null),
  );
  const [draggedPath, setDraggedPath] = useState<string | null>(null);

  const loadFile = useCallback(
    async (path: string) => {
      try {
        const result = await readExplorerFile(sessionId, path);
        setTabs((current) =>
          current.map((tab) =>
            tab.path === path && tab.loading
              ? {
                  ...tab,
                  content: result.content,
                  savedContent: result.content,
                  loading: false,
                  error: "",
                }
              : tab,
          ),
        );
      } catch (reason) {
        setTabs((current) =>
          current.map((tab) =>
            tab.path === path && tab.loading
              ? {
                  ...tab,
                  loading: false,
                  error:
                    reason instanceof Error
                      ? reason.message
                      : "Could not open file",
                }
              : tab,
          ),
        );
      }
    },
    [sessionId],
  );

  useEffect(() => {
    tabs.filter((tab) => tab.loading).forEach((tab) => void loadFile(tab.path));
    // Restored tabs only need loading when this session's editor mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!request) return;
    setTabs((current) => {
      const existing = current.find((tab) => tab.path === request.path);
      if (existing) {
        return request.pinned
          ? current.map((tab) =>
              tab.path === request.path ? { ...tab, preview: false } : tab,
            )
          : current;
      }
      const next = blankTab(request.path, !request.pinned);
      if (!request.pinned) {
        const previewIndex = current.findIndex(
          (tab) => tab.preview && tab.content === tab.savedContent,
        );
        if (previewIndex >= 0) {
          const replaced = [...current];
          replaced[previewIndex] = next;
          return replaced;
        }
      }
      return [...current, next];
    });
    setActivePath(request.path);
    void loadFile(request.path);
  }, [loadFile, request]);

  useEffect(() => {
    const workspace: StoredWorkspace = {
      tabs: tabs.map(({ path, preview }) => ({ path, preview })),
      activePath,
    };
    writeSessionValue(storageKey, JSON.stringify(workspace));
  }, [activePath, storageKey, tabs]);

  const activeTab = tabs.find((tab) => tab.path === activePath) ?? null;
  const activeDirty = Boolean(
    activeTab && activeTab.content !== activeTab.savedContent,
  );

  const pinTab = useCallback((path: string) => {
    setTabs((current) =>
      current.map((tab) =>
        tab.path === path ? { ...tab, preview: false } : tab,
      ),
    );
  }, []);

  const closeTab = useCallback(
    (path: string) => {
      const index = tabs.findIndex((tab) => tab.path === path);
      if (index < 0) return;
      const tab = tabs[index];
      if (
        tab.content !== tab.savedContent &&
        !window.confirm(`Close ${tab.name} without saving?`)
      )
        return;
      const remaining = tabs.filter((candidate) => candidate.path !== path);
      setTabs(remaining);
      if (activePath === path) {
        setActivePath(
          remaining[Math.min(index, remaining.length - 1)]?.path ?? null,
        );
      }
    },
    [activePath, tabs],
  );

  const saveActive = useCallback(async () => {
    if (!activeTab || activeTab.loading || activeTab.saving || !activeDirty)
      return;
    const { path, content } = activeTab;
    setTabs((current) =>
      current.map((tab) =>
        tab.path === path ? { ...tab, saving: true, error: "" } : tab,
      ),
    );
    try {
      await writeExplorerFile(sessionId, path, content);
      setTabs((current) =>
        current.map((tab) =>
          tab.path === path
            ? { ...tab, savedContent: content, saving: false }
            : tab,
        ),
      );
    } catch (reason) {
      setTabs((current) =>
        current.map((tab) =>
          tab.path === path
            ? {
                ...tab,
                saving: false,
                error: reason instanceof Error ? reason.message : "Save failed",
              }
            : tab,
        ),
      );
    }
  }, [activeDirty, activeTab, sessionId]);

  function moveTab(targetPath: string) {
    if (!draggedPath || draggedPath === targetPath) return;
    setTabs((current) => {
      const from = current.findIndex((tab) => tab.path === draggedPath);
      const to = current.findIndex((tab) => tab.path === targetPath);
      if (from < 0 || to < 0) return current;
      const reordered = [...current];
      const [moved] = reordered.splice(from, 1);
      reordered.splice(to, 0, moved);
      return reordered;
    });
    setDraggedPath(null);
  }

  return (
    <section
      css={editorOverlayCss(open)}
      aria-label="Text editor"
      aria-hidden={!open}
      onKeyDownCapture={(event) => {
        if (
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "s"
        ) {
          event.preventDefault();
          void saveActive();
        }
      }}
    >
      <div css={editorTopBarCss}>
        <div css={editorTabsCss} role="tablist" aria-label="Open files">
          {tabs.map((tab) => {
            const dirty = tab.content !== tab.savedContent;
            return (
              <button
                key={tab.path}
                type="button"
                role="tab"
                aria-selected={tab.path === activePath}
                css={editorTabCss(
                  tab.path === activePath,
                  tab.preview,
                  tab.path === draggedPath,
                )}
                title={tab.path}
                draggable
                onClick={() => setActivePath(tab.path)}
                onDoubleClick={() => pinTab(tab.path)}
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  setDraggedPath(tab.path);
                  pinTab(tab.path);
                }}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => moveTab(tab.path)}
                onDragEnd={() => setDraggedPath(null)}
              >
                <span css={editorTabNameCss}>{tab.name}</span>
                {dirty && <span css={dirtyMarkerCss}>●</span>}
                <span
                  css={tabCloseCss}
                  role="button"
                  aria-label={`Close ${tab.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    closeTab(tab.path);
                  }}
                >
                  <VscClose size={14} />
                </span>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          css={editorActionCss()}
          disabled={!activeDirty || activeTab?.saving}
          onClick={() => void saveActive()}
          aria-label="Save active file"
          title="Save (Ctrl+S)"
        >
          <VscSave size={15} />
        </button>
        <button
          type="button"
          css={editorActionCss(true)}
          onClick={onClose}
          aria-label="Close text editor"
          title="Close text editor"
        >
          <VscClose size={18} />
        </button>
      </div>
      <div css={editorBodyCss}>
        {!activeTab ? (
          <div css={editorEmptyCss}>Select a file from the Explorer</div>
        ) : activeTab.loading ? (
          <div css={editorEmptyCss}>Opening {activeTab.name}…</div>
        ) : activeTab.error && !activeTab.content ? (
          <div css={editorErrorCss}>{activeTab.error}</div>
        ) : (
          <Editor
            path={activeTab.path}
            language={languageFor(activeTab.path)}
            value={activeTab.content}
            theme="vs-dark"
            onChange={(value) => {
              const content = value ?? "";
              setTabs((current) =>
                current.map((tab) =>
                  tab.path === activeTab.path
                    ? { ...tab, content, preview: false, error: "" }
                    : tab,
                ),
              );
            }}
            options={{
              automaticLayout: true,
              fontSize: 13,
              minimap: { enabled: true },
              scrollBeyondLastLine: false,
              tabSize: 2,
            }}
          />
        )}
      </div>
      {activeTab && (
        <div css={editorStatusCss}>
          <span css={statusPathCss} title={activeTab.path}>
            {activeTab.path}
          </span>
          {activeTab.error && <span>{activeTab.error}</span>}
          {activeTab.saving && <span css={statusAccentCss}>Saving…</span>}
          {activeDirty && !activeTab.saving && (
            <span css={statusAccentCss}>Modified</span>
          )}
        </div>
      )}
    </section>
  );
}
