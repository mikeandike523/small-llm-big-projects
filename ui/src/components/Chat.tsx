import { css } from "@emotion/react";
import React, { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { type Socket } from "socket.io-client";
import { useStickToBottom } from "use-stick-to-bottom";
import _spin from "../css/_spin";
import scrollbarCss from "../css/scrollBarCss";
import useSocketWiring from "../hooks/useSocketWiring";
import { createSocket } from "../socket";
import LoadingBackdrop from "../subcomponents/Chat/LoadingBackdrop";
import ToolModal from "../subcomponents/Chat/ToolModal";
import { DebugPanel } from "./DebugPanel";
import FormattedCostWithColor from "./FormattedCostWithColor";
import StartupToolCallsCard from "./StartupToolsCard";
import { TerminalPanel } from "./TerminalPanel";
import TurnContainer from "./TurnContainer";

const appLayoutCss = css`
  display: flex;
  flex-direction: row;
  height: 100vh;
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 15px;
  background: #0f0f0f;
  color: #e0e0e0;
`;

const debugPanelWrapperCss = (open: boolean) => css`
  width: ${open ? "20%" : "28px"};
  min-width: ${open ? "160px" : "28px"};
  max-width: ${open ? "320px" : "28px"};
  transition:
    width 0.2s ease,
    min-width 0.2s ease,
    max-width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  height: 100%;
`;

const terminalPanelWrapperCss = (open: boolean) => css`
  width: ${open ? "38%" : "28px"};
  min-width: ${open ? "280px" : "28px"};
  max-width: ${open ? "680px" : "28px"};
  transition:
    width 0.2s ease,
    min-width 0.2s ease,
    max-width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  height: 100%;
`;

const mainAreaCss = css`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
`;

const threadCss = css`
  ${scrollbarCss}
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 28px;
`;

const inputBarCss = css`
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #22304d;
  background: #101722;
`;

const textareaCss = css`
  flex: 1;
  background: #101722;
  color: #f3f6ff;
  border: 1px solid #30405f;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
  &:focus {
    border-color: #8aa4d8;
  }
`;

const sendButtonCss = css`
  position: relative;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 20px;
  font-size: 14px;
  cursor: pointer;
  align-self: flex-end;
  height: 40px;
  overflow: hidden;
  &:disabled {
    background: #1e3a6e;
    cursor: not-allowed;
  }
`;

const stopButtonCss = css`
  background: #1a0a0a;
  color: #c06060;
  border: 1px solid #4a1818;
  border-radius: 8px;
  padding: 0 16px;
  font-size: 14px;
  cursor: pointer;
  font-family: inherit;
  height: 40px;
  align-self: flex-end;
  transition:
    background 0.15s,
    border-color 0.15s;
  &:hover {
    background: #2a1010;
    border-color: #6a2424;
  }
  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
`;

const spinnerCss = css`
  position: absolute;
  inset: 0;
  margin: auto;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

const headerBarCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid #1d2940;
  flex-shrink: 0;
  gap: 12px;
`;

const headerSideCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
`;

const sessionCostCss = css`
  font-size: 10px;
  color: #6a9060;
  font-family: "Consolas", monospace;
  white-space: nowrap;
`;

const statusCss = css`
  font-size: 11px;
  color: #f2f6ff;
  font-family: "Consolas", monospace;
  white-space: nowrap;
`;

const sessionIdCss = css`
  font-size: 10px;
  color: #dbe5ff;
  font-family: "Consolas", monospace;
  white-space: nowrap;
  cursor: default;
`;

const dashboardButtonCss = css`
  background: #101722;
  color: #f3f6ff;
  border: 1px solid #30405f;
  border-radius: 999px;
  width: 28px;
  height: 28px;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition:
    background 0.15s,
    border-color 0.15s,
    transform 0.15s;
  &:hover {
    background: #172235;
    border-color: #6f8fc5;
    transform: translateX(-1px);
  }
`;

// Follow-up behavior footer (below input bar)
const followupFooterCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 16px 6px;
  background: #101722;
  border-top: 1px solid #1a2535;
`;

const followupLabelCss = css`
  font-size: 11px;
  color: #4a6080;
  white-space: nowrap;
  flex-shrink: 0;
`;

const followupOptionCss = (active: boolean) => css`
  background: ${active ? "#1a2f4a" : "transparent"};
  color: ${active ? "#7aaad4" : "#3a5070"};
  border: 1px solid ${active ? "#2a4a6a" : "#1e2e40"};
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 0.1s,
    color 0.1s,
    border-color 0.1s;
  &:hover {
    background: #162840;
    color: #6090b8;
    border-color: #253a52;
  }
`;

export default function Chat() {
  const navigate = useNavigate();
  // Session ID: read from sessionStorage on mount (idempotent — repeated mounts
  // return the same ID; only generates a new UUID the very first time).
  const [sessionId] = useState<string>(() => {
    // URL param takes priority (set by `slbp session new` which opens the browser
    // with ?sessionId=<uuid> pointing to a server-created session).
    const urlId = new URLSearchParams(window.location.search).get("sessionId");
    if (urlId) {
      sessionStorage.setItem("session_id", urlId);
      return urlId;
    }
    let id = sessionStorage.getItem("session_id");
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem("session_id", id);
    }
    return id;
  });

  // Socket: created once per component instance with the stable sessionId.
  // autoConnect:false means it does not connect until socket.connect() is called.
  const socketRef = useRef<Socket | null>(null);
  if (!socketRef.current) {
    socketRef.current = createSocket(sessionId);
  }
  const socket = socketRef.current;

  const [inputText, setInputText] = useState("");
  const [followupBehavior, setFollowupBehavior] = useState<
    "auto" | "follow-up" | "new-task"
  >("auto");
  const [modalContent, setModalContent] = useState<string | null>(null);
  const [debugOpen, setDebugOpen] = useState(false);

  const {
    scrollRef: threadRef,
    contentRef: threadContentRef,
    scrollToBottom,
  } = useStickToBottom();

  const {
    thread,
    startupToolCalls,
    startupDone,
    connected,
    busy,
    setBusy,
    cancelling,
    setCancelling,
    pwd,
    skillsInfo,
    envInfo,
    toolsInfo,
    systemPrompt,
    backendLogs,
    isLoadingBackendState,
    sessionCost,
    terminalOpen,
    setTerminalOpen,
  } = useSocketWiring(socket, scrollToBottom);

  // ---------------------------------------------------------------------------
  // Approval actions
  // ---------------------------------------------------------------------------

  const approve = useCallback((id: string) => {
    socket.emit("approval_response", { id, approved: true });
  }, []);

  const deny = useCallback((id: string) => {
    socket.emit("approval_response", { id, approved: false });
  }, []);

  const denyWithRedirect = useCallback((id: string, message: string) => {
    socket.emit("approval_response", {
      id,
      approved: false,
      redirect_message: message,
    });
  }, []);

  const denyAndStop = useCallback(
    (id: string) => {
      socket.emit("approval_response", { id, approved: false });
      socket.emit("cancel_turn");
      setCancelling(true);
    },
    [socket],
  );

  const cancelTurn = useCallback(() => {
    socket.emit("cancel_turn");
    setCancelling(true);
  }, [socket]);

  // ---------------------------------------------------------------------------
  // Send
  // ---------------------------------------------------------------------------

  const send = useCallback(() => {
    const text = inputText.trim();
    if (!text || busy || !connected) return;

    const clientTurnId = crypto.randomUUID();
    socket.emit("user_message", {
      text,
      clientTurnId,
      followup_behavior: followupBehavior,
    });
    setBusy(true);
    setInputText("");
    scrollToBottom();
  }, [inputText, followupBehavior, busy, connected, scrollToBottom]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div css={appLayoutCss}>
      <LoadingBackdrop isLoadingBackendState={isLoadingBackendState} />

      {/* Debug panel */}
      <div css={debugPanelWrapperCss(debugOpen)}>
        <DebugPanel
          open={debugOpen}
          onToggle={() => setDebugOpen((o) => !o)}
          pwd={pwd}
          sessionId={sessionId}
          envInfo={envInfo}
          skillsInfo={skillsInfo}
          toolsInfo={toolsInfo}
          systemPrompt={systemPrompt}
          backendLogs={backendLogs}
          socket={socket}
        />
      </div>

      {/* Main content area */}
      <div css={mainAreaCss}>
        <ToolModal
          modalContent={modalContent}
          setModalContent={setModalContent}
        />
        <div css={headerBarCss}>
          <div css={headerSideCss}>
            <button
              css={dashboardButtonCss}
              onClick={() => navigate("/")}
              title="Return to dashboard"
              aria-label="Return to dashboard"
            >
              ⌂
            </button>
            <span css={statusCss}>
              {connected ? "●" : "○"} {connected ? "connected" : "disconnected"}
            </span>
          </div>
          <span css={sessionIdCss} title={sessionId}>
            session: {sessionId.slice(0, 8)}
          </span>
          <div css={headerSideCss}>
            {sessionCost !== null && (
              <span
                css={sessionCostCss}
                title="Accumulated session cost (provider-reported)"
              >
                <span style={{ color: "#fff" }}>$</span>
                {FormattedCostWithColor(sessionCost)}
              </span>
            )}{" "}
          </div>
        </div>
        <div css={threadCss} ref={threadRef}>
          <div ref={threadContentRef}>
            {startupToolCalls.length > 0 && (
              <StartupToolCallsCard
                toolCalls={startupToolCalls}
                done={startupDone}
                onViewFull={setModalContent}
              />
            )}
            {thread.map((turn) => (
              <TurnContainer
                key={turn.id}
                turn={turn}
                onViewFull={setModalContent}
                onApprove={approve}
                onDeny={deny}
                onDenyWithRedirect={denyWithRedirect}
                onDenyAndStop={denyAndStop}
              />
            ))}
          </div>
        </div>
        <div css={inputBarCss}>
          <textarea
            css={textareaCss}
            rows={3}
            placeholder="Send a message… (Enter to send, Shift+Enter for newline)"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy || !connected}
          />
          {busy && (
            <button
              css={stopButtonCss}
              onClick={cancelTurn}
              disabled={cancelling}
            >
              {cancelling ? "..." : "Stop"}
            </button>
          )}
          <button
            css={sendButtonCss}
            onClick={send}
            disabled={busy || !connected || !inputText.trim()}
          >
            <span
              css={
                busy
                  ? css`
                      visibility: hidden;
                    `
                  : undefined
              }
            >
              Send
            </span>
            {busy && <span css={spinnerCss} />}
          </button>
        </div>
        <div css={followupFooterCss}>
          <span css={followupLabelCss}>Follow up behavior</span>
          {(["auto", "follow-up", "new-task"] as const).map((opt) => (
            <button
              key={opt}
              css={followupOptionCss(followupBehavior === opt)}
              onClick={() => setFollowupBehavior(opt)}
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

      {/* Terminal panel */}
      <div css={terminalPanelWrapperCss(terminalOpen)}>
        <TerminalPanel
          open={terminalOpen}
          onToggle={() => setTerminalOpen((o) => !o)}
          socket={socket}
          busy={busy}
        />
      </div>
    </div>
  );
}
