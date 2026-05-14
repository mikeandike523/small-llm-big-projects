import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  askButtonCss,
  badgeCss,
  closeTabCss,
  collapsedLabelCss,
  collapsedStripCss,
  emptyCss,
  footerCss,
  headerCss,
  modalActionsRowCss,
  modalBackdropCss,
  modalBodyCss,
  modalBoxCss,
  modalCancelBtnCss,
  modalCloseXCss,
  modalFollowupLabelCss,
  modalFollowupPillCss,
  modalFollowupRowCss,
  modalHeaderRowCss,
  modalSubmitBtnCss,
  modalTextareaCss,
  modalTitleCss,
  newButtonCss,
  panelCss,
  tabBarCss,
  tabButtonCss,
  tabNameCss,
  terminalsCss,
  titleCss,
  toggleButtonCss,
  tooltipCss
} from "../css/TerminalPanel";
import TerminalTab from "../subcomponents/TerminalPanel/TerminalTab";
import { Props, TerminalSessionState, TerminalTabState } from "../types/TerminalPanel";



function getScreenOutput(xterm: Terminal | null): string {
  if (!xterm) return "";
  const buf = xterm.buffer.active;
  const start = buf.viewportY;
  const end = start + xterm.rows - 1;
  const lines: string[] = [];
  for (let i = start; i <= end; i++) {
    const line = buf.getLine(i);
    if (line) lines.push(line.translateToString().trimEnd());
  }
  while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n");
}


function makeTab(
  terminalId: string,
  name: string,
  cmdDisplay: string,
): TerminalTabState {
  return {
    terminalId,
    name,
    cmdDisplay,
    xterm: null,
    fitAddon: null,
    exited: false,
    exitCode: null,
  };
}

export function TerminalPanel({ open, onToggle, socket, busy }: Props) {
  const [tabs, setTabs] = useState<TerminalTabState[]>([]);
  const [activeTabIdx, setActiveTabIdx] = useState(0);
  const tabsRef = useRef<TerminalTabState[]>([]);

  const [askModalOpen, setAskModalOpen] = useState(false);
  const [askModalText, setAskModalText] = useState("");
  const [askModalFollowup, setAskModalFollowup] = useState<
    "auto" | "follow-up" | "new-task"
  >("auto");
  const askTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Single output buffer for all terminals: accumulates data from terminal_output
  // events that arrive before the xterm instance is ready to accept writes.
  // Keyed by terminal_id. Lives outside React state so appending never triggers
  // a re-render or causes the init effect to re-run (which was the root bug).
  const outputBufferRef = useRef<Map<string, string>>(new Map());

  // Polling heuristic: delay terminal creation when panel is animating open.
  const openRef = useRef(open);
  const panelTransitioningRef = useRef(false);
  const pendingCreatedRef = useRef<
    Array<{ terminal_id: string; name: string; cmd_display?: string }>
  >([]);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const panelDivRef = useRef<HTMLDivElement | null>(null);

  // Tooltip state: null = hidden, otherwise track position + text + animation phase.
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    text: string;
    visible: boolean;
  } | null>(null);
  const tooltipHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  useEffect(() => {
    openRef.current = open;
  }, [open]);

  useEffect(
    () => () => {
      if (tooltipHideTimerRef.current)
        clearTimeout(tooltipHideTimerRef.current);
    },
    [],
  );

  const showTooltip = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>, text: string) => {
      if (!text) return;
      if (tooltipHideTimerRef.current) {
        clearTimeout(tooltipHideTimerRef.current);
        tooltipHideTimerRef.current = null;
      }
      const rect = e.currentTarget.getBoundingClientRect();
      setTooltip({
        x: rect.left + rect.width / 2,
        y: rect.top,
        text,
        visible: true,
      });
    },
    [],
  );

  const hideTooltip = useCallback(() => {
    setTooltip((prev) => (prev ? { ...prev, visible: false } : null));
    tooltipHideTimerRef.current = setTimeout(() => setTooltip(null), 85);
  }, []);

  // Sync tabsRef immediately (before the async React re-render) so that socket
  // event handlers always read current xterm references without a render cycle gap.
  const updateTab = useCallback(
    (terminalId: string, patch: Partial<TerminalTabState>) => {
      const next = tabsRef.current.map((tab) =>
        tab.terminalId === terminalId ? { ...tab, ...patch } : tab,
      );
      tabsRef.current = next;
      setTabs(next);
    },
    [],
  );

  const drainBuffer = useCallback((terminalId: string): string => {
    const data = outputBufferRef.current.get(terminalId) ?? "";
    outputBufferRef.current.delete(terminalId);
    return data;
  }, []);

  const clearPoll = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const createTerminalTab = useCallback(
    (terminal_id: string, name: string, cmd_display?: string) => {
      if (tabsRef.current.some((t) => t.terminalId === terminal_id)) return;
      const next = [
        ...tabsRef.current,
        makeTab(terminal_id, name, cmd_display ?? ""),
      ];
      tabsRef.current = next;
      setTabs(next);
      setActiveTabIdx(next.length - 1);
    },
    [],
  );

  useEffect(() => {
    function onTerminalOutput({
      terminal_id,
      data,
    }: {
      terminal_id: string;
      data: string;
    }) {
      const tab = tabsRef.current.find((t) => t.terminalId === terminal_id);
      if (tab?.xterm) {
        tab.xterm.write(data);
      } else {
        // xterm not ready yet (tab unknown or init effect not run) — buffer it.
        outputBufferRef.current.set(
          terminal_id,
          (outputBufferRef.current.get(terminal_id) ?? "") + data,
        );
      }
    }

    function onTerminalExited({
      terminal_id,
      exit_code,
    }: {
      terminal_id: string;
      exit_code: number | null;
    }) {
      const exitText = `\r\n\x1b[33m[process exited with code ${exit_code ?? "?"}]\x1b[0m\r\n`;
      const tab = tabsRef.current.find((t) => t.terminalId === terminal_id);
      if (tab?.xterm) {
        tab.xterm.write(exitText);
      } else {
        outputBufferRef.current.set(
          terminal_id,
          (outputBufferRef.current.get(terminal_id) ?? "") + exitText,
        );
      }
      updateTab(terminal_id, { exited: true, exitCode: exit_code });
    }

    function onTerminalCreated({
      terminal_id,
      name,
      cmd_display,
    }: {
      terminal_id: string;
      name: string;
      cmd_display?: string;
    }) {
      if (panelTransitioningRef.current) {
        if (
          !pendingCreatedRef.current.some((e) => e.terminal_id === terminal_id)
        ) {
          pendingCreatedRef.current.push({ terminal_id, name, cmd_display });
        }
        return;
      }
      createTerminalTab(terminal_id, name, cmd_display);
    }

    function onTerminalOpenPanel() {
      // If the panel was closed, start polling until it has animated to its full width
      // before flushing any queued terminal_created events. This prevents xterm from
      // fitting itself against the narrow mid-transition container.
      if (!openRef.current) {
        panelTransitioningRef.current = true;
        let pollCount = 0;
        clearPoll();
        pollTimerRef.current = setInterval(() => {
          pollCount++;
          const width = panelDivRef.current?.getBoundingClientRect().width ?? 0;
          const expected = Math.min(
            680,
            Math.max(280, window.innerWidth * 0.38),
          );
          if (width >= expected * 0.9 || pollCount >= 6) {
            clearPoll();
            panelTransitioningRef.current = false;
            const pending = pendingCreatedRef.current.splice(0);
            for (const evt of pending) {
              createTerminalTab(evt.terminal_id, evt.name, evt.cmd_display);
            }
          }
        }, 500);
      }
    }

    function onTerminalSessionsState({
      sessions,
    }: {
      sessions: TerminalSessionState[];
    }) {
      const byId = new Map(tabsRef.current.map((tab) => [tab.terminalId, tab]));
      const next = sessions.map((session) => {
        const existing = byId.get(session.terminal_id);
        if (existing)
          return {
            ...existing,
            name: session.name,
            exited: false,
            exitCode: null,
          };
        if (session.snapshot)
          outputBufferRef.current.set(session.terminal_id, session.snapshot);
        return makeTab(
          session.terminal_id,
          session.name,
          session.cmd_display ?? "",
        );
      });
      tabsRef.current = next;
      setTabs(next);
      setActiveTabIdx((idx) => Math.min(idx, Math.max(0, next.length - 1)));
    }

    socket.on("terminal_output", onTerminalOutput);
    socket.on("terminal_exited", onTerminalExited);
    socket.on("terminal_created", onTerminalCreated);
    socket.on("terminal_open_panel", onTerminalOpenPanel);
    socket.on("terminal_sessions_state", onTerminalSessionsState);

    return () => {
      socket.off("terminal_output", onTerminalOutput);
      socket.off("terminal_exited", onTerminalExited);
      socket.off("terminal_created", onTerminalCreated);
      socket.off("terminal_open_panel", onTerminalOpenPanel);
      socket.off("terminal_sessions_state", onTerminalSessionsState);
      clearPoll();
      pendingCreatedRef.current = [];
      panelTransitioningRef.current = false;
    };
  }, [socket, updateTab, createTerminalTab, clearPoll]);

  useEffect(() => {
    if (tabs.length === 0) {
      setActiveTabIdx(0);
      return;
    }
    if (activeTabIdx >= tabs.length) setActiveTabIdx(tabs.length - 1);
  }, [activeTabIdx, tabs.length]);

  useEffect(() => {
    if (!askModalOpen) return;
    const t = setTimeout(() => askTextareaRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [askModalOpen]);

  useEffect(() => {
    if (!askModalOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAskModalOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [askModalOpen]);

  const submitAskModal = useCallback(() => {
    if (busy) return;
    const tab = tabsRef.current[activeTabIdx];
    if (!tab || !askModalText.trim()) return;
    const { terminalId, name, xterm } = tab;
    const screen = getScreenOutput(xterm);
    const screenBlock = screen || "(no output available)";
    const text =
      `Regarding terminal [${terminalId}] (${name}), I have the following question/request.\n\n` +
      `${askModalText.trim()}\n\n` +
      `Use the \`read_open_terminal\` tool with id ${terminalId} or \`last_asked\` if the following data is not sufficient.\n\n` +
      `Terminal Screen Capture:\n\n` +
      `${screenBlock}`;
    socket.emit("terminal_ask_about", { terminal_id: terminalId });
    socket.emit("user_message", {
      text,
      clientTurnId: crypto.randomUUID(),
      followup_behavior: askModalFollowup,
    });
    setAskModalOpen(false);
    setAskModalText("");
    setAskModalFollowup("auto");
  }, [busy, activeTabIdx, askModalText, askModalFollowup, socket]);

  const createTerminal = useCallback(() => {
    socket.emit("terminal_create", {});
  }, [socket]);

  const closeTerminal = useCallback(
    (terminalId: string) => {
      const closingIdx = tabsRef.current.findIndex(
        (tab) => tab.terminalId === terminalId,
      );
      socket.emit("terminal_close", { terminal_id: terminalId });
      const next = tabsRef.current.filter(
        (tab) => tab.terminalId !== terminalId,
      );
      tabsRef.current = next;
      setTabs(next);
      outputBufferRef.current.delete(terminalId);
      setActiveTabIdx((idx) => {
        if (closingIdx < 0 || idx < closingIdx) return idx;
        return Math.max(0, idx - 1);
      });
    },
    [socket],
  );

  if (!open) {
    return (
      <div css={collapsedStripCss}>
        <button
          css={toggleButtonCss}
          onClick={onToggle}
          title="Open terminal panel"
          aria-label="Open terminal panel"
        >
          &lt;
        </button>
        <span css={collapsedLabelCss}>Terminal</span>
        {tabs.length > 0 && <span css={badgeCss}>{tabs.length}</span>}
      </div>
    );
  }

  const activeTab = tabs[activeTabIdx];

  return (
    <div css={panelCss} ref={panelDivRef}>
      <div css={headerCss}>
        <span css={titleCss}>Terminal</span>
        <button
          css={toggleButtonCss}
          onClick={onToggle}
          title="Close terminal panel"
          aria-label="Close terminal panel"
        >
          &gt;
        </button>
      </div>
      <div css={tabBarCss}>
        {tabs.map((tab, idx) => (
          <button
            key={tab.terminalId}
            css={tabButtonCss(idx === activeTabIdx, tab.exited)}
            onClick={() => setActiveTabIdx(idx)}
            onMouseEnter={(e) => showTooltip(e, tab.cmdDisplay)}
            onMouseLeave={hideTooltip}
          >
            <span css={tabNameCss}>
              {tab.name || tab.terminalId}
              {tab.exited ? " (exited)" : ""}
            </span>
            <span
              css={closeTabCss}
              role="button"
              aria-label={`Close ${tab.name || tab.terminalId}`}
              onClick={(event) => {
                event.stopPropagation();
                closeTerminal(tab.terminalId);
              }}
            >
              x
            </span>
          </button>
        ))}
        <button css={newButtonCss} onClick={createTerminal}>
          + New
        </button>
      </div>
      {activeTab ? (
        <div css={terminalsCss}>
          {tabs.map((tab, idx) => (
            <TerminalTab
              key={tab.terminalId}
              tab={tab}
              active={idx === activeTabIdx}
              panelOpen={open}
              socket={socket}
              updateTab={updateTab}
              drainBuffer={drainBuffer}
            />
          ))}
        </div>
      ) : (
        <div css={emptyCss}>
          <button css={newButtonCss} onClick={createTerminal}>
            + New terminal
          </button>
        </div>
      )}
      {activeTab && (
        <div css={footerCss}>
          <button css={askButtonCss} onClick={() => setAskModalOpen(true)}>
            Ask about this terminal
          </button>
        </div>
      )}
      {tooltip && (
        <div
          css={tooltipCss(tooltip.visible)}
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
      {askModalOpen && (
        <>
          <div css={modalBackdropCss} onClick={() => setAskModalOpen(false)} />
          <div
            css={modalBoxCss}
            role="dialog"
            aria-modal="true"
            aria-label="Ask about this terminal"
          >
            <div css={modalHeaderRowCss}>
              <span css={modalTitleCss}>Ask about this terminal</span>
              <button
                css={modalCloseXCss}
                onClick={() => setAskModalOpen(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div css={modalBodyCss}>
              <textarea
                ref={askTextareaRef}
                css={modalTextareaCss}
                placeholder="Type your question or request..."
                value={askModalText}
                onChange={(e) => setAskModalText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey))
                    submitAskModal();
                }}
                rows={4}
              />
              <div css={modalFollowupRowCss}>
                <span css={modalFollowupLabelCss}>Follow-up</span>
                {(["auto", "follow-up", "new-task"] as const).map((opt) => (
                  <button
                    key={opt}
                    css={modalFollowupPillCss(askModalFollowup === opt)}
                    onClick={() => setAskModalFollowup(opt)}
                  >
                    {opt === "auto"
                      ? "auto-detect"
                      : opt === "follow-up"
                        ? "force-follow-up"
                        : "force-new-task"}
                  </button>
                ))}
              </div>
            </div>
            <div css={modalActionsRowCss}>
              <button
                css={modalCancelBtnCss}
                onClick={() => setAskModalOpen(false)}
              >
                Cancel
              </button>
              <button
                css={modalSubmitBtnCss(!askModalText.trim() || busy)}
                disabled={!askModalText.trim() || busy}
                onClick={submitAskModal}
              >
                Send to Agent
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
