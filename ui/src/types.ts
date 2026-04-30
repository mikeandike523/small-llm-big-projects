// Shared types for the session/turn model

export interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  wasStubbed?: boolean
  streamingResult?: string  // live output chunks before result arrives
  startedAt?: number        // ms timestamp — set after approval, before execute
  finishedAt?: number       // ms timestamp — set when result arrives
}

export interface TodoItem {
  item_path: string
  text: string
  status: 'open' | 'closed'
  children?: TodoItem[]
}

export interface ApprovalItem {
  id: string
  tool_name: string
  args: Record<string, unknown>
  resolved?: { approved: boolean }
}

export interface SubturnMeta {
  id: string
  userText: string
  startExchangeIdx: number  // index of first exchange in the flat exchanges array
  isContinuation: boolean
  detailedSummary?: string  // compaction string; undefined when subturn had no tool calls
}

export interface LLMExchange {
  assistantContent: string
  reasoning: string       // native reasoning tokens (model.reasoning) — immediate
  iratThinking: string    // IRAT-converted text-as-thinking — flushed after watchdog
  toolCalls: ToolCallEntry[]
  isFinal: boolean
}

export interface Turn {
  id: string
  userText: string          // first subturn's user text (for display/compat)
  taskTitle?: string        // Short LLM-generated title, arrives asynchronously
  loadedSkills?: string[]   // Fully resolved skill names active for this turn
  subturns: SubturnMeta[]   // metadata for each subturn segment
  exchanges: LLMExchange[]  // flat array across all subturns
  todoItems: TodoItem[]
  approvalItems: ApprovalItem[]
  impossible?: string       // legacy: was_impossible display
  cancelled?: string
  completed: boolean
  // Live state (only meaningful on current/in-progress turn):
  streaming: boolean
  isInterimStreaming: boolean
  interimShowCharCount: boolean
  interimCharCount: number
  interrupted?: boolean
  // Stop-and-redirect state (local only, not replayed from backend):
  stopRedirectState?: 'widget-open' | 'redirected'
  stopRedirectText?: string
}
