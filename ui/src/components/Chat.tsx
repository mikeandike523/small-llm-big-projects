import { css } from "@emotion/react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { type Socket } from "socket.io-client";
import { useStickToBottom } from "use-stick-to-bottom";
import {
  appLayoutCss,
  dashboardButtonCss,
  debugPanelWrapperCss,
  followupFooterCss,
  followupLabelCss,
  followupOptionCss,
  headerBarCss,
  headerSideCss,
  inputBarCss,
  mainAreaCss,
  sendButtonCss,
  sessionCostCss,
  sessionIdCss,
  spinnerCss,
  statusCss,
  stopButtonCss,
  terminalPanelWrapperCss,
  textareaCss,
  threadCss,
} from "../css/Chat";
import useSocketWiring from "../hooks/useSocketWiring";
import { fetchToolPreviewConfig } from "../api/toolPreviewConfig";
import { createSocket } from "../socket";
import LoadingBackdrop from "../subcomponents/Chat/LoadingBackdrop";
import ToolModal from "../subcomponents/Chat/ToolModal";
import { DebugPanel } from "./DebugPanel";
import FormattedCostWithColor from "./FormattedCostWithColor";
import ContextUsageBar from "./ContextUsageBar";
import StartupToolCallsCard from "./StartupToolsCard";
import { TerminalPanel } from "./TerminalPanel";
import TurnContainer from "./TurnContainer";

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

  // Prime the tool-preview widget config once on session-page load, so approval
  // bubbles know which tools/actions render a diff preview (no hard-coded list).
  useEffect(() => {
    fetchToolPreviewConfig();
  }, []);

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
    sessionProfile,
    setSessionProfile,
    approvalMode,
    setApprovalMode,
    contextUsageData,
    terminalOpen,
    setTerminalOpen,
  } = useSocketWiring(socket, scrollToBottom);

  // Electron's tab strip has no browser chrome to read a title from, so it
  // listens for the native page-title-updated event -- setting document.title
  // is the only hook needed to drive it (no custom IPC).
  useEffect(() => {
    const latestTitle = [...thread].reverse().find((t) => t.taskTitle)?.taskTitle;
    document.title = latestTitle ?? "New Session";
  }, [thread]);

  const [profiles, setProfiles] = useState<string[]>([]);
  const [approvalModes, setApprovalModes] = useState<string[]>([
    "default",
    "auto-accept-edits",
    "full-auto",
  ]);
  const [profileChanging, setProfileChanging] = useState(false);
  const [approvalModeChanging, setApprovalModeChanging] = useState(false);

  // Fetch available profile names for the dropdown once on mount.
  React.useEffect(() => {
    fetch("/api/session-defaults")
      .then((r) => r.json())
      .then((d) => {
        if (Array.isArray(d.profiles)) setProfiles(d.profiles);
        if (Array.isArray(d.approval_modes)) setApprovalModes(d.approval_modes);
      })
      .catch(() => {});
  }, []);

  async function handleProfileChange(newProfile: string) {
    if (profileChanging || busy || newProfile === sessionProfile) return;
    setProfileChanging(true);
    try {
      await fetch(`/api/sessions/${sessionId}/profile`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_name: newProfile || null }),
      });
      setSessionProfile(newProfile || null);
    } catch {
      // silently ignore — user can retry
    } finally {
      setProfileChanging(false);
    }
  }

  async function handleApprovalModeChange(newMode: string) {
    if (approvalModeChanging || busy || newMode === approvalMode) return;
    setApprovalModeChanging(true);
    try {
      await fetch(`/api/sessions/${sessionId}/approval-mode`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_mode: newMode }),
      });
      setApprovalMode(newMode);
    } catch {
      // silently ignore — user can retry
    } finally {
      setApprovalModeChanging(false);
    }
  }

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
          {contextUsageData && <ContextUsageBar data={contextUsageData} />}
          <div css={headerSideCss}>
            {profiles.length > 0 && (
              <select
                value={sessionProfile ?? ""}
                onChange={(e) => handleProfileChange(e.target.value)}
                disabled={profileChanging || busy}
                title="Session profile (takes effect on next turn)"
                style={{
                  background: "#101722",
                  border: "1px solid #2a3a6e",
                  borderRadius: 4,
                  color: sessionProfile ? "#a0b8f0" : "#666",
                  fontFamily: "inherit",
                  fontSize: 11,
                  padding: "3px 6px",
                  cursor: profileChanging || busy ? "not-allowed" : "pointer",
                  opacity: profileChanging ? 0.5 : 1,
                }}
              >
                {profiles.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            )}
            <select
              value={approvalMode}
              onChange={(e) => handleApprovalModeChange(e.target.value)}
              disabled={approvalModeChanging || busy}
              title="Approval mode (takes effect on next subturn)"
              style={{
                background: "#101722",
                border: "1px solid #2a3a6e",
                borderRadius: 4,
                color: approvalMode ? "#a0b8f0" : "#666",
                fontFamily: "inherit",
                fontSize: 11,
                padding: "3px 6px",
                cursor: approvalModeChanging || busy ? "not-allowed" : "pointer",
                opacity: approvalModeChanging ? 0.5 : 1,
              }}
            >
              {approvalModes.map((mode) => (
                <option key={mode} value={mode}>
                  {mode}
                </option>
              ))}
            </select>
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
          <div ref={threadContentRef} css={css`display:flex;flex-direction:column;gap:28px;`}>
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
