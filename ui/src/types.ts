// Shared types for the session/turn model

export interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  wasStubbed?: boolean
}

export interface TodoItem {
  item_number: number
  text: string
  status: 'open' | 'closed'
  sub_list?: TodoItem[]
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
  approvalItem?: ApprovalItem
  impossible?: string
  completed: boolean
  // Live state (only meaningful on current/in-progress turn):
  streaming: boolean
  isInterimStreaming: boolean
  interimCharCount: number
  interrupted?: boolean
}
