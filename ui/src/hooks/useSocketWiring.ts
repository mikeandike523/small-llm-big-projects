import { useState, useCallback, useEffect, useRef } from "react";
import type { Socket } from "socket.io-client";
import type {
  Turn,
  Subturn,
  ToolCallEntry,
  TodoItem,
  ApprovalItem,
  PatchRewriteState,
  HeartbeatSettings,
  SubturnOrigin,
} from "../types";
import { DEFAULT_HEARTBEAT_SETTINGS, toSubturnOrigin } from "../types";
import type { BackendLogEntry, BackendLogContent } from "../types/DebugPanel";
import { wireHistoryLoad, type HistoryProgress } from "./historyLoad";

const MAX_LOGS = 100;

function newTurn(
  id: string,
  userText: string,
  origin: SubturnOrigin,
  subturnId?: string,
): Turn {
  const stId = subturnId ?? crypto.randomUUID();
  return {
    id,
    subturns: [{ id: stId, userText, origin, exchanges: [] }],
    todoItems: [],
    approvalItems: [],
    completed: false,
    streaming: true,
    isInterimStreaming: false,
    interimShowCharCount: false,
    interimCharCount: 0,
  };
}

function emptyExchange() {
  return {
    assistantContent: "",
    reasoning: "",
    iratThinking: "",
    toolCalls: [],
    isFinal: false as const,
  };
}

function updateToolCallById(
  t: Turn,
  toolCallId: string,
  updater: (tc: ToolCallEntry) => ToolCallEntry,
): Turn {
  return {
    ...t,
    subturns: t.subturns.map((st) => ({
      ...st,
      exchanges: st.exchanges.map((ex) => ({
        ...ex,
        toolCalls: ex.toolCalls.map((tc) =>
          tc.id === toolCallId ? updater(tc) : tc,
        ),
      })),
    })),
  };
}

export default function useSocketWiring(
  socket: Socket,
  scrollToBottom: () => void,
) {
  const [thread, setThread] = useState<Turn[]>([]);
  const [startupToolCalls, setStartupToolCalls] = useState<ToolCallEntry[]>([]);
  const [startupDone, setStartupDone] = useState(false);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadCustomSkillsTools, setLoadCustomSkillsTools] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [pwd, setPwd] = useState<string>("");
  const [skillsInfo, setSkillsInfo] = useState<{
    enabled: boolean;
    count: number;
    path: string | null;
    files: string[];
  } | null>(null);
  const [envInfo, setEnvInfo] = useState<{
    os: string;
    shell: string;
    initialCwd: string;
  } | null>(null);
  const [toolsInfo, setToolsInfo] = useState<{
    totalCount: number;
    builtinCount: number;
    builtinPath: string;
    names: string[];
    customPlugins: { name: string; count: number; path: string }[] | null;
  } | null>(null);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState<string | null>(null);
  const [backendLogs, setBackendLogs] = useState<BackendLogEntry[]>([]);
  // Progressive history load (see historyLoad.ts). While loading, thread-
  // mutating live events are queued in pendingLiveRef and flushed afterwards.
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyProgress, setHistoryProgress] = useState<HistoryProgress>({
    loaded: 0,
    total: null,
  });
  const [historyError, setHistoryError] = useState<string | null>(null);
  const historyLoadingRef = useRef(true);
  const historyLoadIdRef = useRef<string | null>(null);
  const pendingLiveRef = useRef<(() => void)[]>([]);
  const [sessionCost, setSessionCost] = useState<number | null>(null);
  const [sessionProfile, setSessionProfile] = useState<string | null>(null);
  const sessionProfileRef = useRef<string | null>(null);
  const profileRevisionRef = useRef(0);
  const approvalModeRevisionRef = useRef(0);
  const [approvalMode, setApprovalMode] = useState<string>("default");
  const heartbeatSettingsRevisionRef = useRef(0);
  const [heartbeatSettings, setHeartbeatSettings] = useState<HeartbeatSettings>(
    DEFAULT_HEARTBEAT_SETTINGS,
  );
  const [contextUsageData, setContextUsageData] = useState<{
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number | null;
    known_max_context: number;
  } | null>(null);

  // ---------------------------------------------------------------------------
  // Thread helpers
  // ---------------------------------------------------------------------------

  const updateTurn = useCallback(
    (turnId: string, updater: (t: Turn) => Turn) => {
      setThread((prev) => prev.map((t) => (t.id === turnId ? updater(t) : t)));
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Replay processor
  // ---------------------------------------------------------------------------

  const applyReplayEvent = useCallback(
    (type: string, data: Record<string, unknown>) => {
      const turnId = (data.turn_id as string | undefined) ?? "";

      switch (type) {
        case "turn_start": {
          const id = data.turn_id as string;
          const userText = data.user_text as string;
          const subturnId = data.subturn_id as string | undefined;
          const origin = toSubturnOrigin(data.origin);
          setThread((prev) => {
            if (prev.some((t) => t.id === id)) {
              // Continuation: append new subturn to existing turn
              return prev.map((t) => {
                if (t.id !== id) return t;
                // Already applied (e.g. the subturn is in the loaded history).
                if (subturnId && t.subturns.some((st) => st.id === subturnId))
                  return t;
                const newSt: Subturn = {
                  id: subturnId ?? crypto.randomUUID(),
                  userText,
                  origin,
                  exchanges: [],
                };
                return {
                  ...t,
                  subturns: [...t.subturns, newSt],
                  completed: false,
                  streaming: false,
                };
              });
            } else {
              return [
                ...prev,
                {
                  ...newTurn(id, userText, origin, subturnId),
                  streaming: false,
                },
              ];
            }
          });
          break;
        }
        case "replay_content_snapshot": {
          const subturnId = data.subturn_id as string;
          const exchangeIdx = data.exchange_idx as number;
          const assistantContent = (data.assistant_content as string) ?? "";
          const reasoning = (data.reasoning as string) ?? "";
          updateTurn(turnId, (t) => {
            const subturns = [...t.subturns];
            const stIdx = subturns.findIndex((st) => st.id === subturnId);
            if (stIdx < 0) return t;
            const st = { ...subturns[stIdx] };
            const exchanges = [...st.exchanges];
            while (exchanges.length <= exchangeIdx)
              exchanges.push(emptyExchange());
            exchanges[exchangeIdx] = {
              ...exchanges[exchangeIdx],
              assistantContent,
              reasoning,
            };
            st.exchanges = exchanges;
            subturns[stIdx] = st;
            return { ...t, subturns };
          });
          break;
        }
        case "tool_call": {
          const tc: ToolCallEntry = {
            id: data.id as string,
            name: data.name as string,
            args: data.args as Record<string, unknown>,
          };
          updateTurn(turnId, (t) => {
            const subturns = [...t.subturns];
            const lastIdx = subturns.length - 1;
            if (lastIdx < 0) return t;
            const lastSt = { ...subturns[lastIdx] };
            const exchanges = [...lastSt.exchanges];
            const lastExIdx = exchanges.length - 1;
            if (lastExIdx >= 0 && !exchanges[lastExIdx].isFinal) {
              if (!exchanges[lastExIdx].toolCalls.some((e) => e.id === tc.id)) {
                exchanges[lastExIdx] = {
                  ...exchanges[lastExIdx],
                  toolCalls: [...exchanges[lastExIdx].toolCalls, tc],
                };
              }
            } else {
              exchanges.push({ ...emptyExchange(), toolCalls: [tc] });
            }
            lastSt.exchanges = exchanges;
            subturns[lastIdx] = lastSt;
            return { ...t, subturns };
          });
          break;
        }
        case "tool_call_start": {
          const id = data.id as string;
          const startedAt = data.started_at as number;
          updateTurn(turnId, (t) => ({
            ...t,
            subturns: t.subturns.map((st) => ({
              ...st,
              exchanges: st.exchanges.map((ex) => ({
                ...ex,
                toolCalls: ex.toolCalls.map((tc) =>
                  tc.id === id ? { ...tc, startedAt } : tc,
                ),
              })),
            })),
          }));
          break;
        }
        case "tool_result": {
          const id = data.id as string;
          const result = data.result as string;
          const finishedAt = data.finished_at as number | undefined;
          updateTurn(turnId, (t) => ({
            ...t,
            subturns: t.subturns.map((st) => ({
              ...st,
              exchanges: st.exchanges.map((ex) => ({
                ...ex,
                toolCalls: ex.toolCalls.map((tc) =>
                  tc.id === id
                    ? {
                        ...tc,
                        result,
                        ...(finishedAt !== undefined ? { finishedAt } : {}),
                      }
                    : tc,
                ),
              })),
            })),
          }));
          break;
        }
        case "irat_thinking_clear": {
          const subturnId = data.subturn_id as string;
          const idx = data.exchange_idx as number;
          updateTurn(turnId, (t) => {
            const subturns = [...t.subturns];
            const stIdx = subturns.findIndex((st) => st.id === subturnId);
            if (stIdx < 0) return t;
            const st = { ...subturns[stIdx] };
            const exchanges = [...st.exchanges];
            if (exchanges[idx]) {
              exchanges[idx] = { ...exchanges[idx], iratThinking: "" };
            }
            st.exchanges = exchanges;
            subturns[stIdx] = st;
            return { ...t, subturns };
          });
          break;
        }
        case "subturn_compaction": {
          const subturnId = data.subturn_id as string;
          const compaction = data.compaction as string;
          updateTurn(turnId, (t) => ({
            ...t,
            subturns: t.subturns.map((st) =>
              st.id === subturnId ? { ...st, detailedSummary: compaction } : st,
            ),
          }));
          break;
        }
        case "begin_interim_stream":
          updateTurn(turnId, (t) => ({
            ...t,
            isInterimStreaming: true,
            interimShowCharCount: !!data.show_char_count,
          }));
          break;
        case "begin_final_summary":
          updateTurn(turnId, (t) => {
            const subturns = [...t.subturns];
            const lastIdx = subturns.length - 1;
            if (lastIdx < 0) return t;
            const lastSt = { ...subturns[lastIdx] };
            const exchanges = [...lastSt.exchanges];
            if (exchanges.length > 0) {
              exchanges[exchanges.length - 1] = {
                ...exchanges[exchanges.length - 1],
                isInterim: true,
              };
            }
            lastSt.exchanges = exchanges;
            subturns[lastIdx] = lastSt;
            return { ...t, isInterimStreaming: false, subturns };
          });
          break;
        case "todo_list_update":
          updateTurn(turnId, (t) => ({
            ...t,
            todoItems: data.items as TodoItem[],
          }));
          break;
        case "approval_request": {
          const item: ApprovalItem = {
            id: data.id as string,
            tool_name: data.tool_name as string,
            args: data.args as Record<string, unknown>,
            subturnId: (data.subturn_id as string | undefined) ?? undefined,
          };
          updateTurn(turnId, (t) => ({
            ...t,
            approvalItems: [...t.approvalItems, item],
          }));
          break;
        }
        case "approval_resolved": {
          const approved = data.approved as boolean;
          const id = data.id as string;
          updateTurn(turnId, (t) => ({
            ...t,
            approvalItems: t.approvalItems.map((a) =>
              a.id === id ? { ...a, resolved: { approved } } : a,
            ),
          }));
          break;
        }
        case "message_done": {
          const content = data.content as string | null;
          updateTurn(turnId, (t) => {
            if (content !== null) {
              const subturns = [...t.subturns];
              const lastIdx = subturns.length - 1;
              if (lastIdx >= 0) {
                const lastSt = { ...subturns[lastIdx] };
                const exchanges = [...lastSt.exchanges];
                if (exchanges.length > 0) {
                  exchanges[exchanges.length - 1] = {
                    ...exchanges[exchanges.length - 1],
                    assistantContent: content,
                    isFinal: true,
                  };
                } else {
                  exchanges.push({
                    ...emptyExchange(),
                    assistantContent: content,
                    isFinal: true,
                  });
                }
                lastSt.exchanges = exchanges;
                subturns[lastIdx] = lastSt;
                return {
                  ...t,
                  completed: true,
                  streaming: false,
                  isInterimStreaming: false,
                  subturns,
                };
              }
            }
            return {
              ...t,
              completed: true,
              streaming: false,
              isInterimStreaming: false,
            };
          });
          break;
        }
        case "error": {
          const message = data.message as string;
          updateTurn(turnId, (t) => {
            const subturns = [...t.subturns];
            const lastIdx = subturns.length - 1;
            if (lastIdx < 0) return { ...t, completed: true, streaming: false };
            const lastSt = { ...subturns[lastIdx] };
            const exchanges = [...lastSt.exchanges];
            if (exchanges.length === 0) {
              exchanges.push({
                ...emptyExchange(),
                assistantContent: `⚠ ${message}`,
                isFinal: true,
              });
            } else {
              exchanges[exchanges.length - 1] = {
                ...exchanges[exchanges.length - 1],
                assistantContent: `⚠ ${message}`,
                isFinal: true,
              };
            }
            lastSt.exchanges = exchanges;
            subturns[lastIdx] = lastSt;
            return { ...t, completed: true, streaming: false, subturns };
          });
          break;
        }
        case "task_title":
          updateTurn(turnId, (t) => ({
            ...t,
            taskTitle: data.title as string,
          }));
          break;
        case "skills_loaded":
          updateTurn(turnId, (t) => ({
            ...t,
            loadedSkills: data.skill_names as string[],
          }));
          break;
        case "pwd_update":
          setPwd(data.path as string);
          break;
        case "patch_rewrite_start": {
          const toolCallId = data.tool_call_id as string;
          const originalArgs = data.original_args as Record<string, unknown>;
          updateTurn(turnId, (t) =>
            updateToolCallById(t, toolCallId, (tc) => ({
              ...tc,
              patchRewrite: {
                status: "in_progress" as const,
                originalArgs,
                attempt: 0,
                maxAttempts: 3,
              },
            })),
          );
          break;
        }
        case "patch_rewrite_attempt": {
          const toolCallId = data.tool_call_id as string;
          const attempt = data.attempt as number;
          const maxAttempts = data.max_attempts as number;
          updateTurn(turnId, (t) =>
            updateToolCallById(t, toolCallId, (tc) => ({
              ...tc,
              patchRewrite: tc.patchRewrite
                ? { ...tc.patchRewrite, attempt, maxAttempts }
                : {
                    status: "in_progress" as const,
                    originalArgs: {},
                    attempt,
                    maxAttempts,
                  },
            })),
          );
          break;
        }
        case "patch_rewrite_done": {
          const toolCallId = data.tool_call_id as string;
          const success = data.success as boolean;
          const finalPatch = (data.final_patch as string | null) ?? null;
          updateTurn(turnId, (t) =>
            updateToolCallById(t, toolCallId, (tc) => {
              const newRewrite: PatchRewriteState = tc.patchRewrite
                ? {
                    ...tc.patchRewrite,
                    status: success ? "success" : "failed",
                    ...(finalPatch !== null ? { finalPatch } : {}),
                  }
                : {
                    status: success ? "success" : "failed",
                    originalArgs: {},
                    attempt: 3,
                    maxAttempts: 3,
                    ...(finalPatch !== null ? { finalPatch } : {}),
                  };
              return {
                ...tc,
                patchRewrite: newRewrite,
                // On success, update args so the second viewer shows the fixed patch.
                ...(success && finalPatch !== null
                  ? { args: { ...tc.args, patch: finalPatch } }
                  : {}),
              };
            }),
          );
          break;
        }
      }
    },
    [updateTurn],
  );

  // ---------------------------------------------------------------------------
  // Socket wiring
  // ---------------------------------------------------------------------------

  useEffect(() => {
    // While history loads, queue thread-mutating live events so they apply on
    // top of the loaded turns instead of racing them (flushed in order).
    function gated<T>(handler: (data: T) => void): (data: T) => void {
      return (data: T) => {
        if (historyLoadingRef.current) {
          pendingLiveRef.current.push(() => handler(data));
        } else {
          handler(data);
        }
      };
    }

    function finishHistoryLoad(error: string | null) {
      historyLoadingRef.current = false;
      const queued = pendingLiveRef.current;
      pendingLiveRef.current = [];
      for (const run of queued) run();
      setHistoryError(error);
      setHistoryLoading(false);
      scrollToBottom();
    }

    function onConnect() {
      setConnected(true);
      setBusy(false);
      setCancelling(false);
      // Every (re)connect rebuilds the thread from the backend.
      historyLoadingRef.current = true;
      historyLoadIdRef.current = null;
      pendingLiveRef.current = [];
      setHistoryLoading(true);
      setHistoryError(null);
      setHistoryProgress({ loaded: 0, total: null });
      setThread([]);
      socket.emit("resume_session");
      socket.emit("get_pwd");
      socket.emit("get_skills_info");
      socket.emit("get_env_info");
      socket.emit("get_system_prompt");
      socket.emit("get_tools_info");
    }
    function onDisconnect() {
      setConnected(false);
    }
    function onPwdUpdate({ path }: { path: string }) {
      setPwd(path);
    }
    function onSkillsInfo(data: {
      enabled: boolean;
      count: number;
      path: string | null;
      files: string[];
    }) {
      setSkillsInfo(data);
    }
    function onEnvInfo(data: {
      os: string;
      shell: string;
      initialCwd: string;
    }) {
      setEnvInfo(data);
    }
    function onToolsInfo(data: {
      totalCount: number;
      builtinCount: number;
      builtinPath: string;
      names: string[];
      customPlugins: { name: string; count: number; path: string }[] | null;
    }) {
      setToolsInfo(data);
    }
    function onSystemPrompt({ text }: { text: string }) {
      setSystemPrompt(text);
    }
    function onSessionCostUpdate({ total_usd }: { total_usd: number }) {
      setSessionCost(total_usd);
    }
    function onContextUsageEvent(data: {
      prompt_tokens: number | null;
      completion_tokens: number | null;
      total_tokens: number | null;
      known_max_context: number | null;
      profile?: string | null;
      profile_revision?: number | null;
    }) {
      if (
        data.profile !== undefined &&
        data.profile !== sessionProfileRef.current
      ) {
        return;
      }
      if (
        data.profile_revision != null &&
        data.profile_revision !== profileRevisionRef.current
      ) {
        return;
      }
      // known_max_context === null is a clear signal (e.g. profile switched to
      // one without a known max) — hide the widget instead of showing stale data.
      if (
        data.known_max_context == null ||
        data.prompt_tokens == null ||
        data.completion_tokens == null
      ) {
        setContextUsageData(null);
      } else {
        setContextUsageData({
          prompt_tokens: data.prompt_tokens,
          completion_tokens: data.completion_tokens,
          total_tokens: data.total_tokens,
          known_max_context: data.known_max_context,
        });
      }
    }
    function onSessionSettingsUpdate(data: {
      profileName: string | null;
      profileRevision: number;
      approvalMode: string;
      approvalModeRevision: number;
      heartbeatSettings?: HeartbeatSettings;
      heartbeatSettingsRevision?: number;
    }) {
      if (data.profileRevision >= profileRevisionRef.current) {
        profileRevisionRef.current = data.profileRevision;
        sessionProfileRef.current = data.profileName;
        setSessionProfile(data.profileName);
        setContextUsageData(null);
      }
      if (data.approvalModeRevision >= approvalModeRevisionRef.current) {
        approvalModeRevisionRef.current = data.approvalModeRevision;
        setApprovalMode(data.approvalMode);
      }
      if (
        data.heartbeatSettings !== undefined &&
        (data.heartbeatSettingsRevision ?? 0) >=
          heartbeatSettingsRevisionRef.current
      ) {
        heartbeatSettingsRevisionRef.current =
          data.heartbeatSettingsRevision ?? 0;
        setHeartbeatSettings(data.heartbeatSettings);
      }
    }
    function onBackendLog(entry: BackendLogEntry) {
      let normalizedEntry: BackendLogEntry | null = entry;

      if (entry.multiple === true) {
        if (!Array.isArray(entry.content) || entry.content.length === 0) {
          normalizedEntry = null;
        } else if (entry.content.length === 1) {
          normalizedEntry = {
            id: entry.id,
            content: entry.content[0] as BackendLogContent,
          };
        }
      }

      if (normalizedEntry === null) return;

      setBackendLogs((prev) => {
        const next = [...prev, normalizedEntry];
        return next.length > MAX_LOGS
          ? next.slice(next.length - MAX_LOGS)
          : next;
      });
    }

    function onStartupToolCall({
      id,
      name,
      args,
    }: {
      id: string;
      name: string;
      args: Record<string, unknown>;
    }) {
      setStartupToolCalls((prev) => [...prev, { id, name, args }]);
    }
    function onStartupToolResult({
      id,
      result,
    }: {
      id: string;
      result: string;
    }) {
      setStartupToolCalls((prev) =>
        prev.map((tc) => (tc.id === id ? { ...tc, result } : tc)),
      );
    }
    function onStartupToolCallsDone() {
      setStartupDone(true);
    }

    // Session state (response to resume_session)
    function onSessionState(data: {
      startupDone?: boolean;
      schemaInvalid?: boolean;
      profileName?: string | null;
      approvalMode?: string;
      profileRevision?: number;
      approvalModeRevision?: number;
      heartbeatSettings?: HeartbeatSettings;
      heartbeatSettingsRevision?: number;
      loadCustomSkillsTools?: boolean;
    }) {
      if (data.schemaInvalid) {
        // Schema mismatch — there is no history to load.
        finishHistoryLoad(null);
        setThread([]);
        setStartupToolCalls([]);
        setStartupDone(false);
        socket.emit("run_startup_tool_calls");
        return;
      }

      if (data.startupDone !== undefined) {
        setStartupDone(data.startupDone);
        if (!data.startupDone) {
          // First-ever session: run startup tools now that we know they haven't run yet
          socket.emit("run_startup_tool_calls");
        }
      }

      if (data.profileName !== undefined) {
        sessionProfileRef.current = data.profileName ?? null;
        setSessionProfile(data.profileName ?? null);
      }
      profileRevisionRef.current = data.profileRevision ?? 0;
      if (data.approvalMode !== undefined) {
        setApprovalMode(data.approvalMode);
      }
      approvalModeRevisionRef.current = data.approvalModeRevision ?? 0;
      if (data.heartbeatSettings !== undefined) {
        setHeartbeatSettings(data.heartbeatSettings);
      }
      heartbeatSettingsRevisionRef.current =
        data.heartbeatSettingsRevision ?? 0;
      if (data.loadCustomSkillsTools !== undefined) {
        setLoadCustomSkillsTools(data.loadCustomSkillsTools);
      }

      // The conversation itself streams in turn by turn (historyLoad.ts).
      const loadId = crypto.randomUUID();
      historyLoadIdRef.current = loadId;
      socket.emit("begin_history_load", { loadId });
    }

    // Shell output snapshot: emitted when browser reconnects during a running host_shell.
    function onShellOutputSnapshot({ output }: { output: string }) {
      setThread((prev) =>
        prev.map((t) => {
          if (!t.streaming) return t;
          return {
            ...t,
            subturns: t.subturns.map((st) => ({
              ...st,
              exchanges: st.exchanges.map((ex) => ({
                ...ex,
                toolCalls: ex.toolCalls.map((tc) =>
                  tc.name === "host_shell" && tc.result === undefined
                    ? { ...tc, streamingResult: output }
                    : tc,
                ),
              })),
            })),
          };
        }),
      );
    }

    // Live event handlers
    function onTurnStart(data: {
      event_id?: string;
      turn_id: string;
      user_text: string;
      subturn_id?: string;
      origin?: string;
    }) {
      const { turn_id: id, user_text: userText, subturn_id: subturnId } = data;
      const origin = toSubturnOrigin(data.origin);
      setThread((prev) => {
        if (prev.some((t) => t.id === id)) {
          // Continuation: append new subturn to existing turn
          return prev.map((t) => {
            if (t.id !== id) return t;
            const known =
              !!subturnId && t.subturns.some((st) => st.id === subturnId);
            const newSt: Subturn = {
              id: subturnId ?? crypto.randomUUID(),
              userText,
              origin,
              exchanges: [],
            };
            return {
              ...t,
              // Already applied when replayed with the loaded history.
              subturns: known ? t.subturns : [...t.subturns, newSt],
              completed: false,
              streaming: true,
              isInterimStreaming: false,
              interimShowCharCount: false,
              interimCharCount: 0,
            };
          });
        } else {
          return [...prev, newTurn(id, userText, origin, subturnId)];
        }
      });
      setBusy(true);
      scrollToBottom();
    }

    function onToken(data: {
      type: "reasoning" | "content" | "irat_thinking";
      text: string;
      turn_id?: string;
    }) {
      const turnId = data.turn_id ?? "";
      if (!turnId) return;
      updateTurn(turnId, (t) => {
        if (!t.streaming) return t;
        if (t.isInterimStreaming && data.type === "content") {
          return {
            ...t,
            interimCharCount: t.interimCharCount + data.text.length,
          };
        }
        const subturns = [...t.subturns];
        const lastStIdx = subturns.length - 1;
        if (lastStIdx < 0) return t;
        const lastSt = { ...subturns[lastStIdx] };
        const exchanges = [...lastSt.exchanges];
        const lastEx = exchanges[exchanges.length - 1];
        const needsNew =
          !lastEx ||
          lastEx.toolCalls.length > 0 ||
          lastEx.isFinal ||
          lastEx.isInterim;
        if (needsNew) {
          exchanges.push({
            assistantContent: data.type === "content" ? data.text : "",
            reasoning: data.type === "reasoning" ? data.text : "",
            iratThinking: data.type === "irat_thinking" ? data.text : "",
            toolCalls: [],
            isFinal: false,
          });
        } else {
          const idx = exchanges.length - 1;
          exchanges[idx] = {
            ...exchanges[idx],
            assistantContent:
              data.type === "content"
                ? exchanges[idx].assistantContent + data.text
                : exchanges[idx].assistantContent,
            reasoning:
              data.type === "reasoning"
                ? exchanges[idx].reasoning + data.text
                : exchanges[idx].reasoning,
            iratThinking:
              data.type === "irat_thinking"
                ? exchanges[idx].iratThinking + data.text
                : exchanges[idx].iratThinking,
          };
        }
        lastSt.exchanges = exchanges;
        subturns[lastStIdx] = lastSt;
        return { ...t, subturns };
      });
    }

    function onBeginInterimStream(data: {
      event_id?: string;
      turn_id?: string;
      show_char_count?: boolean;
    }) {
      applyReplayEvent("begin_interim_stream", data);
    }

    function onBeginFinalSummary(data: {
      event_id?: string;
      turn_id?: string;
    }) {
      applyReplayEvent("begin_final_summary", data);
    }

    function onIratThinkingClear(data: {
      event_id?: string;
      turn_id?: string;
      subturn_id: string;
      exchange_idx: number;
    }) {
      applyReplayEvent("irat_thinking_clear", data);
    }

    function onSubturnCompaction(data: {
      event_id?: string;
      turn_id?: string;
      subturn_id: string;
      compaction: string;
    }) {
      applyReplayEvent("subturn_compaction", data);
    }

    function onToolCall(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      name: string;
      args: Record<string, unknown>;
    }) {
      applyReplayEvent("tool_call", data);
    }

    function onToolCallStart(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      started_at: number;
    }) {
      applyReplayEvent("tool_call_start", data);
    }

    function onToolResultChunk(data: {
      turn_id?: string;
      id: string;
      chunk: string;
    }) {
      const turnId = data.turn_id ?? "";
      updateTurn(turnId, (t) => ({
        ...t,
        subturns: t.subturns.map((st) => ({
          ...st,
          exchanges: st.exchanges.map((ex) => ({
            ...ex,
            toolCalls: ex.toolCalls.map((tc) =>
              tc.id === data.id
                ? {
                    ...tc,
                    streamingResult: (tc.streamingResult ?? "") + data.chunk,
                  }
                : tc,
            ),
          })),
        })),
      }));
    }

    function onToolResult(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      result: string;
      started_at?: number;
      finished_at?: number;
    }) {
      applyReplayEvent("tool_result", data);
    }

    function onMessageDone(data: {
      event_id?: string;
      turn_id?: string;
      content: string | null;
    }) {
      applyReplayEvent("message_done", data);
      setBusy(false);
      setCancelling(false);
    }

    function onError(data: {
      event_id?: string;
      turn_id?: string;
      message: string;
    }) {
      if (data.turn_id) applyReplayEvent("error", data);
      setBusy(false);
    }

    function onTodoListUpdate(data: {
      event_id?: string;
      turn_id?: string;
      items: TodoItem[];
    }) {
      applyReplayEvent("todo_list_update", data);
    }

    function onApprovalRequest(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      tool_name: string;
      args: Record<string, unknown>;
    }) {
      applyReplayEvent("approval_request", data);
    }

    function onApprovalResolved(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      approved: boolean;
    }) {
      applyReplayEvent("approval_resolved", data);
    }

    function onTerminalOpenPanel() {
      setTerminalOpen(true);
    }

    function onPatchRewriteStart(data: {
      event_id?: string;
      turn_id?: string;
      tool_call_id: string;
      original_args: Record<string, unknown>;
    }) {
      applyReplayEvent("patch_rewrite_start", data);
    }

    function onPatchRewriteAttempt(data: {
      event_id?: string;
      turn_id?: string;
      tool_call_id: string;
      attempt: number;
      max_attempts: number;
    }) {
      applyReplayEvent("patch_rewrite_attempt", data);
    }

    function onPatchRewriteDone(data: {
      event_id?: string;
      turn_id?: string;
      tool_call_id: string;
      success: boolean;
      final_patch: string | null;
    }) {
      applyReplayEvent("patch_rewrite_done", data);
    }

    function onTaskTitle(data: { turn_id: string; title: string }) {
      applyReplayEvent("task_title", data);
    }
    function onSkillsLoaded(data: { turn_id: string; skill_names: string[] }) {
      applyReplayEvent("skills_loaded", data);
    }

    // Thread-mutating live events, queued while history loads.
    const liveThreadHandlers = {
      turn_start: gated(onTurnStart),
      token: gated(onToken),
      begin_interim_stream: gated(onBeginInterimStream),
      begin_final_summary: gated(onBeginFinalSummary),
      irat_thinking_clear: gated(onIratThinkingClear),
      subturn_compaction: gated(onSubturnCompaction),
      tool_call: gated(onToolCall),
      tool_call_start: gated(onToolCallStart),
      tool_result_chunk: gated(onToolResultChunk),
      tool_result: gated(onToolResult),
      message_done: gated(onMessageDone),
      error: gated(onError),
      todo_list_update: gated(onTodoListUpdate),
      approval_request: gated(onApprovalRequest),
      approval_resolved: gated(onApprovalResolved),
      shell_output_snapshot: gated(onShellOutputSnapshot),
      patch_rewrite_start: gated(onPatchRewriteStart),
      patch_rewrite_attempt: gated(onPatchRewriteAttempt),
      patch_rewrite_done: gated(onPatchRewriteDone),
      task_title: gated(onTaskTitle),
      skills_loaded: gated(onSkillsLoaded),
    };

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    socket.on("pwd_update", onPwdUpdate);
    socket.on("skills_info", onSkillsInfo);
    socket.on("env_info", onEnvInfo);
    socket.on("tools_info", onToolsInfo);
    socket.on("system_prompt", onSystemPrompt);
    socket.on("session_cost_update", onSessionCostUpdate);
    socket.on("context_usage_event", onContextUsageEvent);
    socket.on("session_settings_update", onSessionSettingsUpdate);
    socket.on("backend_log", onBackendLog);
    socket.on("startup_tool_call", onStartupToolCall);
    socket.on("startup_tool_result", onStartupToolResult);
    socket.on("startup_tool_calls_done", onStartupToolCallsDone);
    socket.on("session_state", onSessionState);
    socket.on("terminal_open_panel", onTerminalOpenPanel);
    for (const [event, handler] of Object.entries(liveThreadHandlers)) {
      socket.on(event, handler);
    }
    const unwireHistoryLoad = wireHistoryLoad(socket, {
      loadIdRef: historyLoadIdRef,
      setThread,
      setProgress: setHistoryProgress,
      setBusy,
      applyReplayEvent,
      finish: finishHistoryLoad,
    });

    // Connect after all handlers are registered so we never miss the connect event
    socket.connect();

    return () => {
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      socket.off("pwd_update", onPwdUpdate);
      socket.off("skills_info", onSkillsInfo);
      socket.off("env_info", onEnvInfo);
      socket.off("tools_info", onToolsInfo);
      socket.off("system_prompt", onSystemPrompt);
      socket.off("session_cost_update", onSessionCostUpdate);
      socket.off("context_usage_event", onContextUsageEvent);
      socket.off("session_settings_update", onSessionSettingsUpdate);
      socket.off("backend_log", onBackendLog);
      socket.off("startup_tool_call", onStartupToolCall);
      socket.off("startup_tool_result", onStartupToolResult);
      socket.off("startup_tool_calls_done", onStartupToolCallsDone);
      socket.off("session_state", onSessionState);
      socket.off("terminal_open_panel", onTerminalOpenPanel);
      for (const [event, handler] of Object.entries(liveThreadHandlers)) {
        socket.off(event, handler);
      }
      unwireHistoryLoad();
      socket.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [socket, applyReplayEvent, updateTurn]);

  return {
    thread,
    startupToolCalls,
    startupDone,
    connected,
    busy,
    setBusy,
    loadCustomSkillsTools,
    cancelling,
    setCancelling,
    pwd,
    skillsInfo,
    envInfo,
    toolsInfo,
    systemPrompt,
    backendLogs,
    historyLoading,
    historyProgress,
    historyError,
    sessionCost,
    sessionProfile,
    setSessionProfile,
    approvalMode,
    setApprovalMode,
    heartbeatSettings,
    setHeartbeatSettings,
    contextUsageData,
    setContextUsageData,
    terminalOpen,
    setTerminalOpen,
  };
}
