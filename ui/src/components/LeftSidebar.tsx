/** @jsxImportSource @emotion/react */
import { useState } from "react";
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
import { DebugPanel } from "./DebugPanel";
import FileExplorer from "./FileExplorer";

type SidebarView = "explorer" | "debug";
type Props = Omit<DebugPanelProps, "open">;
const WIDTH_STORAGE_KEY = "slbp:left-sidebar-width";
const DEFAULT_PANEL_WIDTH = 360;
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 640;

function clampWidth(value: number): number {
  return Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, value));
}

function storedPanelWidth(): number {
  const stored = Number(sessionStorage.getItem(WIDTH_STORAGE_KEY));
  return Number.isFinite(stored) && stored > 0
    ? clampWidth(stored)
    : DEFAULT_PANEL_WIDTH;
}

export default function LeftSidebar(props: Props) {
  const [activeView, setActiveView] = useState<SidebarView | null>(null);
  const [panelWidth, setPanelWidth] = useState(storedPanelWidth);

  function toggleView(view: SidebarView) {
    setActiveView((current) => (current === view ? null : view));
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
          setPanelWidth(clampWidth(element.offsetWidth));
        }}
        onResizeStop={(_event, _direction, element) => {
          const width = clampWidth(element.offsetWidth);
          setPanelWidth(width);
          sessionStorage.setItem(WIDTH_STORAGE_KEY, String(width));
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
            />
          </div>
          <div
            css={sidebarViewCss(activeView === "debug")}
            aria-hidden={activeView !== "debug"}
          >
            <DebugPanel open={activeView === "debug"} {...props} />
          </div>
        </div>
      </Resizable>
    </aside>
  );
}
