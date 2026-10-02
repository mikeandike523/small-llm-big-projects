/**
 * Loading session turns on demand (client side).
 *
 * The session page shows one turn per page, so turns are fetched one at a
 * time with an acknowledged `load_turn` socket call (history_loader.py):
 *
 *   load_turn {latest: true} -> {turnIds, turn, running, events, liveTodoItems}
 *   load_turn {turnId}       -> {turnId, turn}
 *   (either may instead return {error})
 *
 * `events` are the running turn's not-yet-saved socket events, replayed on top
 * of the latest turn. Live socket events that arrive meanwhile are queued by
 * the caller (see `gated` in useSocketWiring) and flushed once that load ends.
 */
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

export type ReplayEvent = {
  id: string;
  type: string;
  data: Record<string, unknown>;
};

export type LatestTurnResult = {
  turnIds: string[];
  turn: BackendTurn | null;
  running: boolean;
  events: ReplayEvent[];
  liveTodoItems: TodoItem[] | null;
};

export type TurnResult = { turnId: string; turn: BackendTurn | null };

const LOAD_TIMEOUT_MS = 30_000;

/** Ask the backend for one turn (or the latest); rejects with a message. */
export function requestTurn(
  socket: Socket,
  request: { latest: true },
): Promise<LatestTurnResult>;
export function requestTurn(
  socket: Socket,
  request: { turnId: string },
): Promise<TurnResult>;
export function requestTurn(
  socket: Socket,
  request: { latest: true } | { turnId: string },
): Promise<LatestTurnResult | TurnResult> {
  return new Promise((resolve, reject) => {
    socket
      .timeout(LOAD_TIMEOUT_MS)
      .emit(
        "load_turn",
        request,
        (
          err: Error | null,
          res: (LatestTurnResult | TurnResult) & { error?: string },
        ) => {
          if (err) reject(new Error("Timed out loading session history."));
          else if (res?.error) reject(new Error(res.error));
          else resolve(res);
        },
      );
  });
}

/** Did the turn the unsaved events belong to already finish within them? */
export function turnEndedIn(events: ReplayEvent[]): boolean {
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
