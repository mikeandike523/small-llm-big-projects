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

  // Keep callbacks from acting on an inactive, display:none terminal without
  // recreating the ResizeObserver on every tab switch.
  const activeRef = useRef(active);
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

    // Defer fit so layout has settled, while avoiding an inactive terminal's
    // display:none container.
    requestAnimationFrame(() => {
      if (activeRef.current) safeFit(containerRef.current, fitAddon);
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

  // Opening the drawer or selecting this tab should focus it, but mounting a
  // terminal behind the closed clipping viewport must not steal focus.
  useEffect(() => {
    if (panelOpen && active) tab.xterm?.focus();
  }, [active, panelOpen, tab.xterm]);

  // Fit whenever the tab becomes active. The fixed-width drawer rail remains
  // measurable while clipped closed, so opening does not require another fit.
  useEffect(() => {
    if (!active) return;
    safeFit(containerRef.current, tab.fitAddon);
  }, [active, tab.fitAddon]);

  // Container resize → refit, but only when this tab is the visible one.
  // ResizeObserver is recreated only when fitAddon changes (via refs for the
  // active guard so we don't recreate it on every tab switch).
  useEffect(() => {
    if (!containerRef.current || !tab.fitAddon) return;
    const obs = new ResizeObserver(() => {
      if (activeRef.current) safeFit(containerRef.current, tab.fitAddon);
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [tab.fitAddon]);

  return <div ref={containerRef} css={terminalContainerCss(active)} />;
}
