/** @jsxImportSource @emotion/react */
import { useEffect, useState } from "react";
import {
  collapsedLabelCss,
  collapsedStripCss,
  headerCss,
  headerTitleCss,
  memTabContainerCss,
  memTabFooterCss,
  memTabScrollCss,
  modalBodyCss,
  modalCardCss,
  modalCloseButtonCss,
  modalFooterCss,
  modalFooterDeletedCss,
  modalFooterModifiedCss,
  modalHeaderCss,
  modalLoadingWrapCss,
  modalOverlayCss,
  modalSpinnerCss,
  modalTitleCss,
  panelCss,
  placeholderCss,
  promptPanelCss,
  refreshSpinnerCss,
  rowCss,
  saveTracesBtnCss,
  saveTracesStatusCss,
  tabBarCss,
  tabButtonCss,
  tabContentAreaCss,
  tabPanelCss,
  toggleButtonCss,
} from "../css/DebugPanel";
import BackendLogsTab from "../subcomponents/DebugPanel/BackendLogsTab";
import DirtyTab from "../subcomponents/DebugPanel/DirtyTab";
import MemTabFooter from "../subcomponents/DebugPanel/MemTabFooter";
import SessionMemTab from "../subcomponents/DebugPanel/SessionMemTab";
import SystemTab from "../subcomponents/DebugPanel/SystemTab";
import { MemKeyEvent, Props } from "../types/DebugPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tab system
// ---------------------------------------------------------------------------

type TabId = "system" | "session" | "prompt" | "logs" | "dirty";

const TABS: { id: TabId; label: string }[] = [
  { id: "system", label: "System Info" },
  { id: "session", label: "Session Mem" },
  { id: "prompt", label: "Sys Prompt" },
  { id: "logs", label: "Backend Logs" },
  { id: "dirty", label: "Dirty" },
];

// ---------------------------------------------------------------------------
// DebugPanel
// ---------------------------------------------------------------------------

interface MemModal {
  key: string;
  value: string;
  loading: boolean;
  notification: "modified" | "deleted" | null;
}

export function DebugPanel({
  open,
  onToggle,
  pwd,
  sessionId,
  envInfo,
  skillsInfo,
  toolsInfo,
  systemPrompt,
  backendLogs,
  socket,
}: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("system");
  const [sessionMemKeys, setSessionMemKeys] = useState<string[]>([]);
  const [sessionMemLoading, setSessionMemLoading] = useState(false);
  const [lastSessionMemEvent, setLastSessionMemEvent] =
    useState<MemKeyEvent | null>(null);
  const [memModal, setMemModal] = useState<MemModal | null>(null);
  const [savingTraces, setSavingTraces] = useState(false);
  const [traceSaveStatus, setTraceSaveStatus] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const [dirtyFiles, setDirtyFiles] = useState<string[]>([]);
  const [seenFiles, setSeenFiles] = useState<string[]>([]);
  const [dirtyMemKeys, setDirtyMemKeys] = useState<string[]>([]);
  const [seenMemKeys, setSeenMemKeys] = useState<string[]>([]);

  // Listen for session and project memory socket events
  useEffect(() => {
    function onSessionMemoryKeys({ keys }: { keys: string[] }) {
      setSessionMemKeys(keys);
      setSessionMemLoading(false);
    }
    function onSessionMemoryValue({
      key,
      value,
      found,
    }: {
      key: string;
      value: string;
      found: boolean;
    }) {
      setMemModal((prev) => {
        if (!prev || prev.key !== key) return prev;
        return {
          key,
          value: found ? value : "(key not found)",
          loading: false,
          notification: null,
        };
      });
    }
    function onSessionMemoryKeyEvent({
      key,
      type,
    }: {
      key: string;
      type: "modified" | "deleted";
    }) {
      // Always update the last-event footer regardless of whether the modal is open
      setLastSessionMemEvent({ key, type });
      // Also notify the modal if it's showing this key
      setMemModal((prev) => {
        if (!prev || prev.key !== key) return prev;
        return { ...prev, notification: type };
      });
    }
    function onTracesSaved({
      count,
      filename,
    }: {
      count: number;
      filename: string | null;
    }) {
      setSavingTraces(false);
      if (count === 0) {
        setTraceSaveStatus({ ok: true, message: "No buffered traces." });
      } else {
        setTraceSaveStatus({
          ok: true,
          message: `Saved ${count} trace${count !== 1 ? "s" : ""} → ${filename}`,
        });
      }
    }
    function onTracesSaveError({ message }: { message: string }) {
      setSavingTraces(false);
      setTraceSaveStatus({ ok: false, message: `Error: ${message}` });
    }
    function onDirtyCacheUpdate({
      files,
      seen_files,
      mem_keys,
      seen_mem_keys,
    }: {
      files: string[];
      seen_files: string[];
      mem_keys: string[];
      seen_mem_keys: string[];
    }) {
      setDirtyFiles(files);
      setSeenFiles(seen_files ?? []);
      setDirtyMemKeys(mem_keys);
      setSeenMemKeys(seen_mem_keys ?? []);
    }

    socket.on("session_memory_keys_update", onSessionMemoryKeys);
    socket.on("session_memory_value", onSessionMemoryValue);
    socket.on("session_memory_key_event", onSessionMemoryKeyEvent);
    socket.on("traces_saved", onTracesSaved);
    socket.on("traces_save_error", onTracesSaveError);
    socket.on("dirty_cache_update", onDirtyCacheUpdate);
    socket.emit("get_dirty_cache");
    return () => {
      socket.off("session_memory_keys_update", onSessionMemoryKeys);
      socket.off("session_memory_value", onSessionMemoryValue);
      socket.off("session_memory_key_event", onSessionMemoryKeyEvent);
      socket.off("traces_saved", onTracesSaved);
      socket.off("traces_save_error", onTracesSaveError);
      socket.off("dirty_cache_update", onDirtyCacheUpdate);
    };
  }, []);

  // Fetch keys (with loading state) when tabs become active
  useEffect(() => {
    if (open && activeTab === "session") {
      setSessionMemLoading(true);
      socket.emit("get_session_memory_keys");
    }
  }, [open, activeTab]);

  function refreshMemoryKeys() {
    setSessionMemLoading(true);
    socket.emit("get_session_memory_keys");
  }

  function viewMemoryValue(key: string) {
    setMemModal({ key, value: "", loading: true, notification: null });
    socket.emit("get_session_memory_value", { key });
  }

  function saveTraces() {
    setSavingTraces(true);
    setTraceSaveStatus(null);
    socket.emit("save_traces");
  }

  if (!open) {
    return (
      <div css={collapsedStripCss}>
        <button
          css={toggleButtonCss}
          onClick={onToggle}
          title="Open debug panel"
        >
          »
        </button>
        <span css={collapsedLabelCss}>Debug</span>
      </div>
    );
  }

  return (
    <>
      {memModal && (
        <div css={modalOverlayCss} onClick={() => setMemModal(null)}>
          <div css={modalCardCss} onClick={(e) => e.stopPropagation()}>
            <div css={modalHeaderCss}>
              <span css={modalTitleCss}>[session] {memModal.key}</span>
              <button
                css={modalCloseButtonCss}
                onClick={() => setMemModal(null)}
              >
                ×
              </button>
            </div>
            <div css={modalBodyCss}>
              {memModal.loading ? (
                <div css={modalLoadingWrapCss}>
                  <div css={modalSpinnerCss} />
                </div>
              ) : (
                memModal.value
              )}
            </div>
            {memModal.notification && (
              <div css={modalFooterCss}>
                {memModal.notification === "deleted" ? (
                  <span css={modalFooterDeletedCss}>
                    Memory item deleted since modal opened
                  </span>
                ) : (
                  <span
                    css={modalFooterModifiedCss}
                    onClick={() => {
                      setMemModal((prev) =>
                        prev
                          ? { ...prev, loading: true, notification: null }
                          : prev,
                      );
                      socket.emit("get_session_memory_value", {
                        key: memModal.key,
                      });
                    }}
                  >
                    Memory item modified since modal opened — click to refetch
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <div css={panelCss}>
        <div css={headerCss}>
          <span css={headerTitleCss}>Debug</span>
          <button
            css={toggleButtonCss}
            onClick={onToggle}
            title="Close debug panel"
          >
            «
          </button>
        </div>

        <div css={tabBarCss}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              css={tabButtonCss(activeTab === tab.id)}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div css={tabContentAreaCss}>
          <div css={tabPanelCss(activeTab === "system")}>
            <SystemTab
              pwd={pwd}
              sessionId={sessionId}
              envInfo={envInfo}
              skillsInfo={skillsInfo}
              toolsInfo={toolsInfo}
            />
            <div css={rowCss}>
              <button
                css={saveTracesBtnCss}
                onClick={saveTraces}
                disabled={savingTraces}
              >
                {savingTraces && <span css={refreshSpinnerCss} />}
                Save Fine-Tuning Traces
              </button>
              {traceSaveStatus && (
                <span css={saveTracesStatusCss(traceSaveStatus.ok)}>
                  {traceSaveStatus.message}
                </span>
              )}
            </div>
          </div>

          {/* Session memory tab: flex column with scrollable content + fixed footer */}
          <div css={memTabContainerCss(activeTab === "session")}>
            <div css={memTabScrollCss}>
              <SessionMemTab
                keys={sessionMemKeys}
                dirtyMemKeys={new Set(dirtyMemKeys)}
                seenMemKeys={new Set(seenMemKeys)}
                onRefresh={refreshMemoryKeys}
                onView={viewMemoryValue}
                loading={sessionMemLoading}
              />
            </div>
            <div css={memTabFooterCss}>
              <MemTabFooter event={lastSessionMemEvent} />
            </div>
          </div>

          <div css={promptPanelCss(activeTab === "prompt")}>
            {systemPrompt !== null ? (
              systemPrompt
            ) : (
              <span css={placeholderCss}>Not yet received.</span>
            )}
          </div>
          <BackendLogsTab logs={backendLogs} visible={activeTab === "logs"} />

          <div css={tabPanelCss(activeTab === "dirty")}>
            <DirtyTab
              files={dirtyFiles}
              seenFiles={seenFiles.filter((f) => !dirtyFiles.includes(f))}
              memKeys={dirtyMemKeys}
              seenMemKeys={seenMemKeys.filter((k) => !dirtyMemKeys.includes(k))}
            />
          </div>
        </div>
      </div>
    </>
  );
}
