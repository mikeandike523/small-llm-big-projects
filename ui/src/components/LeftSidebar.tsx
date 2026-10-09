/** @jsxImportSource @emotion/react */
import { useEffect, useMemo, useRef, useState } from "react";
import { Resizable } from "re-resizable";
import { GiAnt } from "react-icons/gi";
import { VscFiles } from "react-icons/vsc";
import {
  activityBarCss,
  activityButtonCss,
  panelAreaCss,
  resizeHandleCss,
  sidebarCss,
  sidebarViewCss,
} from "../css/LeftSidebar";
import type { Props as DebugPanelProps } from "../types/DebugPanel";
import type {
  EditorOpenRequest,
  ExplorerRevealRequest,
} from "../types/FileExplorer";
import { readSessionValue, writeSessionValue } from "../utils/sessionStorage";
import { DebugPanel } from "./DebugPanel";
import FileExplorer from "./FileExplorer";
import FileEditorPanel from "./FileEditorPanel";

type SidebarView = "explorer" | "debug";
type Props = Omit<DebugPanelProps, "open">;
const WIDTH_STORAGE_KEY = "slbp:left-sidebar-width";
const VIEW_STORAGE_KEY = "slbp:left-sidebar-view";
const DEFAULT_PANEL_WIDTH = 360;
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 640;

function clampWidth(value: number): number {
  return Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, value));
}

function storedPanelWidth(): number {
  const stored = Number(readSessionValue(WIDTH_STORAGE_KEY));
  return Number.isFinite(stored) && stored > 0
    ? clampWidth(stored)
    : DEFAULT_PANEL_WIDTH;
}

function storedActiveView(): SidebarView | null {
  const stored = readSessionValue(VIEW_STORAGE_KEY);
  return stored === "explorer" || stored === "debug" ? stored : null;
}

function createWidthStorageThrottle(waitMs: number) {
  let lastWrite = 0;
  let timeout: ReturnType<typeof setTimeout> | null = null;
  let pendingWidth: number | null = null;

  function commit(width: number) {
    lastWrite = Date.now();
    pendingWidth = null;
    writeSessionValue(WIDTH_STORAGE_KEY, String(width));
  }

  function schedule(width: number) {
    pendingWidth = width;
    const remaining = waitMs - (Date.now() - lastWrite);
    if (remaining <= 0) {
      if (timeout) clearTimeout(timeout);
      timeout = null;
      commit(width);
    } else if (!timeout) {
      timeout = setTimeout(() => {
        timeout = null;
        if (pendingWidth !== null) commit(pendingWidth);
      }, remaining);
    }
  }

  schedule.flush = () => {
    if (timeout) clearTimeout(timeout);
    timeout = null;
    if (pendingWidth !== null) commit(pendingWidth);
  };
  schedule.cancel = () => {
    if (timeout) clearTimeout(timeout);
    timeout = null;
    pendingWidth = null;
  };
  return schedule;
}

export default function LeftSidebar(props: Props) {
  const [activeView, setActiveView] = useState<SidebarView | null>(
    storedActiveView,
  );
  const [panelWidth, setPanelWidth] = useState(storedPanelWidth);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorRequest, setEditorRequest] = useState<EditorOpenRequest | null>(
    null,
  );
  const [explorerRevealRequest, setExplorerRevealRequest] =
    useState<ExplorerRevealRequest | null>(null);
  const explorerRevealSequence = useRef(0);
  const persistWidth = useMemo(() => createWidthStorageThrottle(120), []);

  useEffect(
    () => () => {
      persistWidth.flush();
      persistWidth.cancel();
    },
    [persistWidth],
  );

  function toggleView(view: SidebarView) {
    const next = activeView === view ? null : view;
    setActiveView(next);
    writeSessionValue(VIEW_STORAGE_KEY, next ?? "closed");
  }

  return (
    <aside css={sidebarCss} aria-label="Sidebar">
      <nav css={activityBarCss} aria-label="Sidebar views">
        <button
          type="button"
          css={activityButtonCss(activeView === "explorer")}
          onClick={() => toggleView("explorer")}
          aria-label="File Explorer"
          aria-pressed={activeView === "explorer"}
          title="File Explorer"
        >
          <VscFiles size={25} />
        </button>
        <button
          type="button"
          css={activityButtonCss(activeView === "debug")}
          onClick={() => toggleView("debug")}
          aria-label="Debug"
          aria-pressed={activeView === "debug"}
          title="Debug"
        >
          <GiAnt size={27} />
        </button>
      </nav>

      <Resizable
        size={{ width: activeView ? panelWidth : 0, height: "100%" }}
        minWidth={activeView ? MIN_PANEL_WIDTH : 0}
        maxWidth={activeView ? MAX_PANEL_WIDTH : 0}
        enable={{ right: activeView !== null }}
        onResize={(_event, _direction, element) => {
          const width = clampWidth(element.offsetWidth);
          setPanelWidth(width);
          persistWidth(width);
        }}
        onResizeStop={(_event, _direction, element) => {
          const width = clampWidth(element.offsetWidth);
          setPanelWidth(width);
          persistWidth(width);
          persistWidth.flush();
        }}
        handleComponent={{ right: <div css={resizeHandleCss} /> }}
        style={{ flexShrink: 0, overflow: "visible" }}
      >
        <div css={panelAreaCss}>
          <div
            css={sidebarViewCss(activeView === "explorer")}
            aria-hidden={activeView !== "explorer"}
          >
            <FileExplorer
              active={activeView === "explorer"}
              initialCwd={props.envInfo?.initialCwd ?? ""}
              sessionId={props.sessionId}
              editorOpen={editorOpen}
              revealRequest={explorerRevealRequest}
              onToggleEditor={() => setEditorOpen((value) => !value)}
              onOpenFile={(request) => {
                setEditorRequest(request);
                setEditorOpen(true);
              }}
            />
          </div>
          <div
            css={sidebarViewCss(activeView === "debug")}
            aria-hidden={activeView !== "debug"}
          >
            <DebugPanel open={activeView === "debug"} {...props} />
          </div>
          <FileEditorPanel
            open={activeView === "explorer" && editorOpen}
            sessionId={props.sessionId}
            request={editorRequest}
            onClose={() => setEditorOpen(false)}
            onRevealFile={(path) => {
              explorerRevealSequence.current += 1;
              setExplorerRevealRequest({
                path,
                requestId: explorerRevealSequence.current,
              });
            }}
          />
        </div>
      </Resizable>
    </aside>
  );
}
