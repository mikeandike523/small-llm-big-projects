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
  timedOut?: boolean
}

export interface LLMExchange {
  assistantContent: string
  reasoning: string
  toolCalls: ToolCallEntry[]
  isFinal: boolean
}

export interface Turn {
  id: string
  userText: string
  exchanges: LLMExchange[]
  todoItems: TodoItem[]
  approvalItems: ApprovalItem[]
  impossible?: string
  cancelled?: string
  completed: boolean
  // Live state (only meaningful on current/in-progress turn):
  streaming: boolean
  isInterimStreaming: boolean
  interimCharCount: number
  interrupted?: boolean
}
