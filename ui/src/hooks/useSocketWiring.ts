import { useState, useCallback, useEffect } from "react";
import type { Socket } from "socket.io-client";
import type {
  Turn,
  Subturn,
  ToolCallEntry,
  TodoItem,
  ApprovalItem,
  PatchRewriteState,
} from "../types";
import type { BackendLogEntry, BackendLogContent } from "../types/DebugPanel";

const MAX_LOGS = 100;

function newTurn(id: string, userText: string, subturnId?: string): Turn {
  const stId = subturnId ?? crypto.randomUUID();
  return {
    id,
    subturns: [{ id: stId, userText, exchanges: [] }],
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

type BackendExchange = {
  assistant_content: string;
  reasoning: string;
  tool_calls: {
    id: string;
    name: string;
    args: Record<string, unknown>;
    result?: string;
    was_stubbed?: boolean;
    started_at?: number;
    finished_at?: number;
  }[];
  is_final: boolean;
};

type BackendSubturn = {
  id: string;
  user_text: string;
  exchanges: BackendExchange[];
  detailed_summary?: string;
};

function mapExchange(ex: BackendExchange) {
  return {
    assistantContent: ex.assistant_content,
    reasoning: ex.reasoning,
    iratThinking: "",
    toolCalls: ex.tool_calls.map((tc) => ({
      id: tc.id,
      name: tc.name,
      args: tc.args,
      result: tc.result,
      wasStubbed: tc.was_stubbed,
      startedAt: tc.started_at ?? undefined,
      finishedAt: tc.finished_at ?? undefined,
    })),
    isFinal: ex.is_final,
  };
}

function backendTurnToFrontendTurn(d: {
  id: string;
  subturns?: BackendSubturn[];
  // legacy format (schema v3 and below)
  user_text?: string;
  exchanges?: BackendExchange[];
  task_title?: string;
  todo_snapshot: TodoItem[];
  was_impossible?: boolean;
  impossible_reason?: string;
  completed: boolean;
}): Turn {
  const subturns: Subturn[] =
    d.subturns && d.subturns.length > 0
      ? d.subturns.map((st) => ({
          id: st.id,
          userText: st.user_text,
          exchanges: st.exchanges.map(mapExchange),
          detailedSummary: st.detailed_summary ?? undefined,
        }))
      : [
          {
            id: crypto.randomUUID(),
            userText: d.user_text ?? "",
            exchanges: (d.exchanges ?? []).map(mapExchange),
          },
        ];

  return {
    id: d.id,
    taskTitle: d.task_title ?? undefined,
    subturns,
    todoItems: d.todo_snapshot ?? [],
    approvalItems: [],
    impossible: d.was_impossible
      ? (d.impossible_reason ?? "Task was impossible")
      : undefined,
    completed: d.completed,
    streaming: false,
    isInterimStreaming: false,
    interimShowCharCount: false,
    interimCharCount: 0,
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
  const [isLoadingBackendState, setIsLoadingBackendState] = useState(false);
  const [sessionCost, setSessionCost] = useState<number | null>(null);
  const [sessionProfile, setSessionProfile] = useState<string | null>(null);
  const [approvalMode, setApprovalMode] = useState<string>("default");
  const [contextUsageData, setContextUsageData] = useState<{
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number | null;
    known_max_context: number;
  } | null>(null);

  // ---------------------------------------------------------------------------
  // lastEventId — persisted to sessionStorage
  // ---------------------------------------------------------------------------

  const getLastEventId = () => sessionStorage.getItem("lastEventId") ?? "0-0";
  const updateLastEventId = (id: string) => {
    sessionStorage.setItem("lastEventId", id);
  };

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
          setThread((prev) => {
            if (prev.some((t) => t.id === id)) {
              // Continuation: append new subturn to existing turn
              return prev.map((t) => {
                if (t.id !== id) return t;
                const newSt: Subturn = {
                  id: subturnId ?? crypto.randomUUID(),
                  userText,
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
                { ...newTurn(id, userText, subturnId), streaming: false },
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
    function onConnect() {
      setConnected(true);
      setBusy(false);
      setCancelling(false);
      setIsLoadingBackendState(true);
      // Mark any streaming turns as interrupted (they'll be cleared by event replay if still running)
      setThread((prev) =>
        prev.map((t) =>
          t.streaming ? { ...t, streaming: false, interrupted: true } : t,
        ),
      );
      socket.emit("resume_session", { lastEventId: getLastEventId() });
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
    }) {
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
      completedTurns?: unknown[];
      currentTurn?: unknown;
      schemaInvalid?: boolean;
      profileName?: string | null;
      approvalMode?: string;
    }) {
      if (data.schemaInvalid) {
        // Schema mismatch — no event_replay will follow, so clear loading now
        setIsLoadingBackendState(false);
        setThread([]);
        setStartupToolCalls([]);
        setStartupDone(false);
        socket.emit("run_startup_tool_calls");
        return;
      }

      // Rebuild thread from completed turns
      const turns: Turn[] = data.completedTurns
        ? (
            data.completedTurns as Parameters<
              typeof backendTurnToFrontendTurn
            >[0][]
          ).map(backendTurnToFrontendTurn)
        : [];

      // If there is an in-progress turn at restore time, append it as streaming.
      // Event replay will fill in any content/tool-calls that arrived since lastEventId.
      // If the agent already finished, the replayed message_done will mark it completed.
      if (data.currentTurn) {
        const inProgress = backendTurnToFrontendTurn(
          data.currentTurn as Parameters<typeof backendTurnToFrontendTurn>[0],
        );
        inProgress.streaming = true;
        inProgress.isInterimStreaming = false;
        inProgress.interimShowCharCount = false;
        inProgress.interimCharCount = 0;
        turns.push(inProgress);
        setBusy(true);
      }

      setThread(turns);

      if (data.startupDone !== undefined) {
        setStartupDone(data.startupDone);
        if (!data.startupDone) {
          // First-ever session: run startup tools now that we know they haven't run yet
          socket.emit("run_startup_tool_calls");
        }
      }

      if (data.profileName !== undefined) {
        setSessionProfile(data.profileName ?? null);
      }
      if (data.approvalMode !== undefined) {
        setApprovalMode(data.approvalMode);
      }
    }

    // Event replay (always emitted after session_state, possibly with empty list)
    function onEventReplay({
      events,
      replay_complete,
    }: {
      events: { id: string; type: string; data: Record<string, unknown> }[];
      replay_complete?: boolean;
    }) {
      if (events && events.length > 0) {
        // Clear interrupted state on any streaming turns before replaying
        setThread((prev) =>
          prev.map((t) =>
            t.interrupted ? { ...t, interrupted: false, streaming: true } : t,
          ),
        );

        for (const ev of events) {
          if (ev.data.event_id) updateLastEventId(ev.data.event_id as string);
          applyReplayEvent(ev.type, ev.data);
        }
        updateLastEventId(events[events.length - 1].id);
      }

      // After replay, force scroll to bottom so the user sees the current state.
      if (replay_complete) {
        scrollToBottom();
      }

      // Replay complete — safe to show UI now
      setIsLoadingBackendState(false);
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
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      const { turn_id: id, user_text: userText, subturn_id: subturnId } = data;
      setThread((prev) => {
        if (prev.some((t) => t.id === id)) {
          // Continuation: append new subturn to existing turn
          return prev.map((t) => {
            if (t.id !== id) return t;
            const newSt: Subturn = {
              id: subturnId ?? crypto.randomUUID(),
              userText,
              exchanges: [],
            };
            return {
              ...t,
              subturns: [...t.subturns, newSt],
              completed: false,
              streaming: true,
              isInterimStreaming: false,
              interimShowCharCount: false,
              interimCharCount: 0,
            };
          });
        } else {
          return [...prev, newTurn(id, userText, subturnId)];
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
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("begin_interim_stream", data);
    }

    function onBeginFinalSummary(data: {
      event_id?: string;
      turn_id?: string;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("begin_final_summary", data);
    }

    function onIratThinkingClear(data: {
      event_id?: string;
      turn_id?: string;
      subturn_id: string;
      exchange_idx: number;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("irat_thinking_clear", data);
    }

    function onSubturnCompaction(data: {
      event_id?: string;
      turn_id?: string;
      subturn_id: string;
      compaction: string;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("subturn_compaction", data);
    }

    function onToolCall(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      name: string;
      args: Record<string, unknown>;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("tool_call", data);
    }

    function onToolCallStart(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      started_at: number;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
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
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("tool_result", data);
    }

    function onMessageDone(data: {
      event_id?: string;
      turn_id?: string;
      content: string | null;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("message_done", data);
      setBusy(false);
      setCancelling(false);
    }

    function onError(data: {
      event_id?: string;
      turn_id?: string;
      message: string;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      if (data.turn_id) applyReplayEvent("error", data);
      setBusy(false);
    }

    function onTodoListUpdate(data: {
      event_id?: string;
      turn_id?: string;
      items: TodoItem[];
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("todo_list_update", data);
    }

    function onApprovalRequest(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      tool_name: string;
      args: Record<string, unknown>;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("approval_request", data);
    }

    function onApprovalResolved(data: {
      event_id?: string;
      turn_id?: string;
      id: string;
      approved: boolean;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
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
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("patch_rewrite_start", data);
    }

    function onPatchRewriteAttempt(data: {
      event_id?: string;
      turn_id?: string;
      tool_call_id: string;
      attempt: number;
      max_attempts: number;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("patch_rewrite_attempt", data);
    }

    function onPatchRewriteDone(data: {
      event_id?: string;
      turn_id?: string;
      tool_call_id: string;
      success: boolean;
      final_patch: string | null;
    }) {
      if (data.event_id) updateLastEventId(data.event_id);
      applyReplayEvent("patch_rewrite_done", data);
    }

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    socket.on("pwd_update", onPwdUpdate);
    socket.on("skills_info", onSkillsInfo);
    socket.on("env_info", onEnvInfo);
    socket.on("tools_info", onToolsInfo);
    socket.on("system_prompt", onSystemPrompt);
    socket.on("session_cost_update", onSessionCostUpdate);
    socket.on("context_usage_event", onContextUsageEvent);
    socket.on("backend_log", onBackendLog);
    socket.on("startup_tool_call", onStartupToolCall);
    socket.on("startup_tool_result", onStartupToolResult);
    socket.on("startup_tool_calls_done", onStartupToolCallsDone);
    socket.on("session_state", onSessionState);
    socket.on("event_replay", onEventReplay);
    socket.on("turn_start", onTurnStart);
    socket.on("token", onToken);
    socket.on("begin_interim_stream", onBeginInterimStream);
    socket.on("begin_final_summary", onBeginFinalSummary);
    socket.on("irat_thinking_clear", onIratThinkingClear);
    socket.on("subturn_compaction", onSubturnCompaction);
    socket.on("tool_call", onToolCall);
    socket.on("tool_call_start", onToolCallStart);
    socket.on("tool_result_chunk", onToolResultChunk);
    socket.on("tool_result", onToolResult);
    socket.on("message_done", onMessageDone);
    socket.on("error", onError);
    socket.on("todo_list_update", onTodoListUpdate);
    socket.on("approval_request", onApprovalRequest);
    socket.on("approval_resolved", onApprovalResolved);
    socket.on("shell_output_snapshot", onShellOutputSnapshot);
    socket.on("terminal_open_panel", onTerminalOpenPanel);
    socket.on("patch_rewrite_start", onPatchRewriteStart);
    socket.on("patch_rewrite_attempt", onPatchRewriteAttempt);
    socket.on("patch_rewrite_done", onPatchRewriteDone);
    socket.on("task_title", (data: { turn_id: string; title: string }) => {
      applyReplayEvent("task_title", data);
    });
    socket.on(
      "skills_loaded",
      (data: { turn_id: string; skill_names: string[] }) => {
        applyReplayEvent("skills_loaded", data);
      },
    );

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
      socket.off("backend_log", onBackendLog);
      socket.off("startup_tool_call", onStartupToolCall);
      socket.off("startup_tool_result", onStartupToolResult);
      socket.off("startup_tool_calls_done", onStartupToolCallsDone);
      socket.off("session_state", onSessionState);
      socket.off("event_replay", onEventReplay);
      socket.off("turn_start", onTurnStart);
      socket.off("token", onToken);
      socket.off("begin_interim_stream", onBeginInterimStream);
      socket.off("begin_final_summary", onBeginFinalSummary);
      socket.off("irat_thinking_clear", onIratThinkingClear);
      socket.off("subturn_compaction", onSubturnCompaction);
      socket.off("tool_call", onToolCall);
      socket.off("tool_call_start", onToolCallStart);
      socket.off("tool_result_chunk", onToolResultChunk);
      socket.off("tool_result", onToolResult);
      socket.off("message_done", onMessageDone);
      socket.off("error", onError);
      socket.off("todo_list_update", onTodoListUpdate);
      socket.off("approval_request", onApprovalRequest);
      socket.off("approval_resolved", onApprovalResolved);
      socket.off("shell_output_snapshot", onShellOutputSnapshot);
      socket.off("terminal_open_panel", onTerminalOpenPanel);
      socket.off("patch_rewrite_start", onPatchRewriteStart);
      socket.off("patch_rewrite_attempt", onPatchRewriteAttempt);
      socket.off("patch_rewrite_done", onPatchRewriteDone);
      socket.off("task_title");
      socket.off("skills_loaded");
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
    setContextUsageData,
    terminalOpen,
    setTerminalOpen,
  };
}
