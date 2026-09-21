// Shared types for the session/turn model

export interface HeartbeatSettings {
  enabled: boolean;
  interval_minutes: number;
  instructions: string;
  heartbeat_approval_policy: "wait-for-human" | "force-fail" | "force-approve";
}

export const HEARTBEAT_INTERVALS_MINUTES = [5, 15, 20, 25, 30, 45, 60];
export const HEARTBEAT_APPROVAL_POLICIES: HeartbeatSettings["heartbeat_approval_policy"][] =
  ["wait-for-human", "force-fail", "force-approve"];

export const DEFAULT_HEARTBEAT_SETTINGS: HeartbeatSettings = {
  enabled: false,
  interval_minutes: 30,
  instructions: "",
  heartbeat_approval_policy: "wait-for-human",
};

export interface PatchRewriteState {
  status: "in_progress" | "success" | "failed";
  originalArgs: Record<string, unknown>;
  attempt: number;
  maxAttempts: number;
  finalPatch?: string;
}

export interface ToolCallEntry {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  wasStubbed?: boolean;
  streamingResult?: string; // live output chunks before result arrives
  startedAt?: number; // ms timestamp — set after approval, before execute
  finishedAt?: number; // ms timestamp — set when result arrives
  patchRewrite?: PatchRewriteState;
}

export interface TodoItem {
  item_path: string;
  text: string;
  status: "open" | "closed";
  children?: TodoItem[];
}

export interface ApprovalItem {
  id: string;
  tool_name: string;
  args: Record<string, unknown>;
  resolved?: { approved: boolean };
  subturnId?: string;
}

export interface LLMExchange {
  assistantContent: string;
  reasoning: string; // native reasoning tokens (model.reasoning) — immediate
  iratThinking: string; // IRAT-converted text-as-thinking — flushed after watchdog
  toolCalls: ToolCallEntry[];
  isFinal: boolean;
  isInterim?: boolean; // true after begin_final_summary — prevents onToken appending to this exchange
}

export interface Subturn {
  id: string;
  userText: string;
  exchanges: LLMExchange[];
  detailedSummary?: string; // compaction string; undefined when subturn had no tool calls
}

export interface Turn {
  id: string;
  taskTitle?: string; // Short LLM-generated title, arrives asynchronously
  loadedSkills?: string[]; // Fully resolved skill names active for this turn
  subturns: Subturn[]; // each subturn owns its exchanges
  todoItems: TodoItem[];
  approvalItems: ApprovalItem[];
  impossible?: string; // legacy: was_impossible display
  completed: boolean;
  // Live state (only meaningful on current/in-progress turn):
  streaming: boolean;
  isInterimStreaming: boolean;
  interimShowCharCount: boolean;
  interimCharCount: number;
  interrupted?: boolean;
}
