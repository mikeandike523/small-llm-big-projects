// Shared types for the session/turn model

export interface HeartbeatSettings {
  enabled: boolean;
  interval_minutes: number;
  instructions: string;
  heartbeat_approval_policy: "wait-for-human" | "force-fail" | "force-approve";
  /** How each heartbeat message is admitted (the chat footer's choices). */
  followup_behavior: "auto" | "follow-up" | "new-task";
}

export const HEARTBEAT_APPROVAL_POLICIES: HeartbeatSettings["heartbeat_approval_policy"][] =
  ["wait-for-human", "force-fail", "force-approve"];

export const DEFAULT_HEARTBEAT_SETTINGS: HeartbeatSettings = {
  enabled: false,
  interval_minutes: 30,
  instructions: "",
  heartbeat_approval_policy: "wait-for-human",
  followup_behavior: "auto",
};

/** Heartbeat follow-up behaviors with the same labels as the chat footer. */
export const HEARTBEAT_FOLLOWUP_BEHAVIORS: {
  value: HeartbeatSettings["followup_behavior"];
  label: string;
}[] = [
  { value: "auto", label: "auto-detect" },
  { value: "follow-up", label: "force-follow-up" },
  { value: "new-task", label: "force-new-task" },
];

export interface EmailSettings {
  enabled: boolean;
  /** The alias this session answers; "" = none (replies to nobody). */
  alias: string;
  agent_name: string;
  /** Normalized addresses; the dialog edits them one per line. */
  allowed_senders: string[];
  email_approval_policy: "wait-for-human" | "force-fail" | "force-approve";
  followup_behavior: "auto" | "follow-up" | "new-task";
  /** Server-set unix time of the current alias claim. */
  alias_claimed_at: number | null;
}

export const DEFAULT_EMAIL_SETTINGS: EmailSettings = {
  enabled: false,
  alias: "",
  agent_name: "",
  allowed_senders: [],
  email_approval_policy: "wait-for-human",
  followup_behavior: "auto",
  alias_claimed_at: null,
};

export type AutomationApprovalPolicy =
  HeartbeatSettings["heartbeat_approval_policy"];

export const AUTOMATION_APPROVAL_POLICIES = HEARTBEAT_APPROVAL_POLICIES;

/** One conversation in an agent's pool: a one-liner on the dashboard. */
export interface AgentPoolSession {
  session_id: string;
  sender_address: string;
  /** From the sender's From header, so unverified. */
  display_name: string | null;
  gmail_thread_id: string;
  /** Subject of the latest email from the sender. */
  subject: string;
  status:
    | "idle"
    | "running"
    | "waiting_approval"
    | "queued"
    | "failed"
    | "cancelled"
    | "interrupted";
}

export interface AgentSummary {
  id: string;
  slug: string;
  /** Null only for agents unregistered before retiring existed. A retired
   * agent keeps its name and email for display but no longer holds them. */
  name: string | null;
  email: string | null;
  enabled: boolean;
  allowed_senders: string[];
  profile_name: string;
  approval_mode: string;
  automation_approval_policy: AutomationApprovalPolicy;
  workspace: string;
  /** Unix seconds. */
  created_at: number;
  /** Unix seconds, or null while the pool is active. */
  retired_at: number | null;
  /** Unix seconds of the newest email in the pool, or null. */
  last_activity_at: number | null;
  sessions: AgentPoolSession[];
}

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

// Who started a subturn; the turn's current owner is its last subturn's origin.
export type SubturnOrigin = "user" | "heartbeat" | "email";

export function toSubturnOrigin(value: unknown): SubturnOrigin {
  return value === "heartbeat" || value === "email" ? value : "user";
}

export interface Subturn {
  id: string;
  userText: string;
  origin: SubturnOrigin;
  exchanges: LLMExchange[];
  detailedSummary?: string; // compaction string; undefined when subturn had no tool calls
  // Streamed thinking characters (display metadata; saved periodically, may lag).
  nativeThinkingChars?: number;
  iratThinkingChars?: number;
  // Ended without an answer (set by the backend when history is loaded).
  interrupted?: boolean;
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
}
