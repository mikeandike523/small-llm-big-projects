import { Socket } from "socket.io-client";
import { TerminalTabState } from "../../types/TerminalPanel";
import { useEffect, useRef } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { terminalContainerCss } from "../../css/TerminalPanel";

function safeFit(container: HTMLDivElement | null, fitAddon: FitAddon | null) {
  if (!container || !fitAddon) return;
  try {
    fitAddon.fit();
  } catch {
    // xterm can briefly have no measurable cell size while layout is settling.
  }
}

export default function TerminalTab({
  tab,
  active,
  panelOpen,
  socket,
  updateTab,
  drainBuffer,
}: {
  tab: TerminalTabState;
  active: boolean;
  panelOpen: boolean;
  socket: Socket;
  updateTab: (terminalId: string, patch: Partial<TerminalTabState>) => void;
  drainBuffer: (terminalId: string) => string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const openedRef = useRef(false);

  // Refs that always hold the latest prop values so rAF and ResizeObserver
  // callbacks never act on stale closures. Initialized from props so they
  // are correct even before the sync effects below have a chance to run.
  const panelOpenRef = useRef(panelOpen);
  const activeRef = useRef(active);
  useEffect(() => {
    panelOpenRef.current = panelOpen;
  }, [panelOpen]);
  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!containerRef.current || openedRef.current) return;
    openedRef.current = true;

    const xterm = new Terminal({
      theme: {
        background: "#0d0d0d",
        foreground: "#e0e0e0",
        cursor: "#8aa4d8",
      },
      fontFamily: "'Consolas', 'Courier New', monospace",
      fontSize: 13,
      scrollback: 5000,
    });
    const fitAddon = new FitAddon();
    xterm.loadAddon(fitAddon);

    // Drain buffered output BEFORE open() — xterm queues writes internally and
    // flushes them atomically on open(), so the terminal never shows a blank frame.
    const pending = drainBuffer(tab.terminalId);
    if (pending) xterm.write(pending);

    xterm.open(containerRef.current);
    xterm.focus();

    const dataDisposable = xterm.onData((data) => {
      socket.emit("terminal_input", { terminal_id: tab.terminalId, data });
    });
    const resizeDisposable = xterm.onResize(({ cols, rows }) => {
      socket.emit("terminal_resize", {
        terminal_id: tab.terminalId,
        rows,
        cols,
      });
    });

    // updateTab syncs tabsRef synchronously, so output events immediately write
    // to this xterm instance instead of going to the buffer.
    updateTab(tab.terminalId, { xterm, fitAddon });

    // Defer fit so the layout has settled. Read refs (not closure values) so
    // we never fit a tab that became inactive or whose panel closed before the
    // frame fired — avoiding a fit on a display:none container.
    requestAnimationFrame(() => {
      if (panelOpenRef.current && activeRef.current)
        safeFit(containerRef.current, fitAddon);
    });

    return () => {
      openedRef.current = false;
      dataDisposable.dispose();
      resizeDisposable.dispose();
      // Null out xterm in tabsRef synchronously BEFORE dispose, so that any
      // output arriving during the StrictMode cleanup+remount window goes to
      // the buffer and gets drained by the next effect run.
      updateTab(tab.terminalId, { xterm: null, fitAddon: null });
      xterm.dispose();
    };
  }, [socket, tab.terminalId, updateTab, drainBuffer]);

  // Fit whenever the tab becomes active or the panel opens. fitAddon in deps
  // so this fires once fitAddon is available after init.
  useEffect(() => {
    if (!panelOpen || !active) return;
    safeFit(containerRef.current, tab.fitAddon);
  }, [active, panelOpen, tab.fitAddon]);

  // Container resize → refit, but only when this tab is the visible one.
  // ResizeObserver is recreated only when fitAddon changes (via refs for the
  // panelOpen/active guards so we don't recreate on every tab switch).
  useEffect(() => {
    if (!containerRef.current || !tab.fitAddon) return;
    const obs = new ResizeObserver(() => {
      if (panelOpenRef.current && activeRef.current)
        safeFit(containerRef.current, tab.fitAddon);
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [tab.fitAddon]);

  return <div ref={containerRef} css={terminalContainerCss(active)} />;
}
