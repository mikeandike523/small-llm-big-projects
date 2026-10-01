/**
 * Progressive session history loading (client side).
 *
 * After `session_state`, the client emits `begin_history_load {loadId}` and the
 * backend streams the conversation turn by turn from MySQL:
 *
 *   history_load_started {loadId, turnIds, running}
 *   history_turn_bundle  {loadId, seq, turn}   (acked after it renders)
 *   history_load_done    {loadId, events, liveTodoItems, error?}
 *
 * `events` are the running turn's not-yet-saved socket events, replayed on top
 * of the loaded turns. Live socket events that arrive meanwhile are queued by
 * the caller (see `gated` in useSocketWiring) and flushed once loading ends.
 */
import type { Dispatch, SetStateAction } from "react";
import type { Socket } from "socket.io-client";
import type { Turn, Subturn, TodoItem } from "../types";
import { toSubturnOrigin } from "../types";

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
  origin?: string;
  exchanges: BackendExchange[];
  detailed_summary?: string;
  native_thinking_chars?: number;
  irat_thinking_chars?: number;
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

export type BackendTurn = {
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
};

export function backendTurnToFrontendTurn(d: BackendTurn): Turn {
  const subturns: Subturn[] =
    d.subturns && d.subturns.length > 0
      ? d.subturns.map((st) => ({
          id: st.id,
          userText: st.user_text,
          origin: toSubturnOrigin(st.origin),
          exchanges: st.exchanges.map(mapExchange),
          detailedSummary: st.detailed_summary ?? undefined,
          nativeThinkingChars: st.native_thinking_chars ?? 0,
          iratThinkingChars: st.irat_thinking_chars ?? 0,
        }))
      : [
          {
            id: crypto.randomUUID(),
            userText: d.user_text ?? "",
            origin: "user",
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

export type HistoryProgress = { loaded: number; total: number | null };

type ReplayEvent = { id: string; type: string; data: Record<string, unknown> };

export type HistoryLoadDeps = {
  /** The load this connection is waiting for; anything else is stale. */
  loadIdRef: { current: string | null };
  setThread: Dispatch<SetStateAction<Turn[]>>;
  setProgress: Dispatch<SetStateAction<HistoryProgress>>;
  setBusy: (busy: boolean) => void;
  applyReplayEvent: (type: string, data: Record<string, unknown>) => void;
  /** End loading: flush queued live events, show `error` if any, scroll. */
  finish: (error: string | null) => void;
};

function updateLastTurn(thread: Turn[], updater: (t: Turn) => Turn): Turn[] {
  if (thread.length === 0) return thread;
  const next = [...thread];
  next[next.length - 1] = updater(next[next.length - 1]);
  return next;
}

/** Did the turn the unsaved events belong to already finish within them? */
function turnEndedIn(events: ReplayEvent[]): boolean {
  let start = -1;
  events.forEach((ev, i) => {
    if (ev.type === "turn_start") start = i;
  });
  return events
    .slice(start + 1)
    .some(
      (ev) =>
        ev.type === "message_done" || (ev.type === "error" && ev.data.turn_id),
    );
}

export function wireHistoryLoad(
  socket: Socket,
  deps: HistoryLoadDeps,
): () => void {
  let expectedTurnIds: string[] = [];
  let received = 0;
  let running = false;

  function onStarted(data: {
    loadId: string;
    turnIds: string[];
    running: boolean;
  }) {
    if (data.loadId !== deps.loadIdRef.current) return;
    expectedTurnIds = data.turnIds;
    received = 0;
    running = data.running;
    deps.setProgress({ loaded: 0, total: data.turnIds.length });
  }

  function onBundle(
    data: { loadId: string; seq: number; turn: BackendTurn },
    ack?: () => void,
  ) {
    if (data.loadId !== deps.loadIdRef.current) {
      ack?.();
      return;
    }
    if (data.seq !== received || data.turn.id !== expectedTurnIds[data.seq]) {
      console.warn("History bundle out of order", {
        seq: data.seq,
        expectedSeq: received,
        turnId: data.turn.id,
        expectedTurnId: expectedTurnIds[data.seq],
      });
    }
    received += 1;
    const turn = backendTurnToFrontendTurn(data.turn);
    deps.setThread((prev) => [...prev, turn]);
    deps.setProgress((p) => ({ ...p, loaded: p.loaded + 1 }));
    // Ack once this turn has rendered, so the backend sends the next one.
    requestAnimationFrame(() => ack?.());
  }

  function onDone(data: {
    loadId: string;
    events: ReplayEvent[];
    liveTodoItems: TodoItem[] | null;
    error?: string;
  }) {
    if (data.loadId !== deps.loadIdRef.current) return;
    if (data.error) {
      deps.finish(data.error);
      return;
    }
    if (running) {
      // The saved todo list belongs to the running turn if it is in MySQL
      // already; newer todo_list_update events below override it.
      const items = data.liveTodoItems ?? [];
      deps.setThread((prev) =>
        updateLastTurn(prev, (t) =>
          t.completed ? t : { ...t, todoItems: items },
        ),
      );
    }
    for (const ev of data.events) deps.applyReplayEvent(ev.type, ev.data);
    if (running && !turnEndedIn(data.events)) {
      deps.setThread((prev) =>
        updateLastTurn(prev, (t) =>
          t.completed ? t : { ...t, streaming: true },
        ),
      );
      deps.setBusy(true);
    }
    deps.finish(null);
  }

  socket.on("history_load_started", onStarted);
  socket.on("history_turn_bundle", onBundle);
  socket.on("history_load_done", onDone);
  return () => {
    socket.off("history_load_started", onStarted);
    socket.off("history_turn_bundle", onBundle);
    socket.off("history_load_done", onDone);
  };
}
