import { create } from 'zustand'

// 单条工具调用记录（附着在 Message 上）
export interface ToolCallEntry {
  id: string
  toolName: string
  toolArgs: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  resultPreview?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string                  // 正式回答文字
  thinkContent: string             // 思考过程（折叠框）
  thinkDone: boolean               // 思考是否已完成（控制折叠）
  toolCalls: ToolCallEntry[]       // 本条消息触发的工具调用列表
  timestamp: Date
}

export interface ActionStatus {
  status: 'running' | 'completed'
  message: string
}

export interface LoopStatusEvent {
  id: string
  phase: string
  message: string
  status: 'running' | 'done' | 'error'
  timestamp: Date
}

export interface StatusTimelineEvent {
  id: string
  seq: number
  kind: 'phase' | 'tool' | 'observation' | 'llm' | 'control'
  status: 'running' | 'done' | 'error'
  phase: string
  message: string
  toolCallId?: string
  timestamp: Date
}

export interface UsageSummary {
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheCreationTokens: number
  estimatedCostUsd: number
}

interface ChatStore {
  messages: Message[]
  isStreaming: boolean
  threadId: string | null
  currentModel: string
  availableModels: string[]
  totalTokensUsed: number
  loopStatus: LoopStatusEvent[]
  statusTimeline: StatusTimelineEvent[]
  usageSummary: UsageSummary

  // 文字追加（正式回答）
  appendTextChunk: (chunk: string) => void
  // 整体替换当前 AI 消息的正式文字（用于内联 tool_call 被识别后修正）
  replaceText: (content: string) => void
  // 思考内容追加
  appendThinkChunk: (chunk: string) => void
  // 思考结束
  markThinkDone: () => void
  // 工具调用：在当前 AI 消息上追加一条
  addToolCallToMessage: (entry: ToolCallEntry) => void
  // 工具调用：更新当前 AI 消息上的某条
  updateToolCallInMessage: (id: string, updates: Partial<ToolCallEntry>) => void

  addUserMessage: (content: string) => void
  finishStream: () => void
  setThreadId: (id: string) => void
  setCurrentModel: (model: string) => void
  setAvailableModels: (models: string[]) => void
  clearMessages: () => void
  addTokensUsed: (count: number) => void
  addLoopStatus: (event: Omit<LoopStatusEvent, 'id' | 'timestamp'>) => void
  pushStatusTimeline: (event: Omit<StatusTimelineEvent, 'id' | 'seq' | 'timestamp'>) => void
  finalizeRunningToolCalls: (finalStatus?: 'done' | 'error') => void
  setUsageSummary: (usage: Partial<UsageSummary>) => void
  clearLoopState: () => void
}
let _idCounter = 0
const genId = () => `msg-${Date.now()}-${++_idCounter}`

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4)
}

function emptyAssistantMessage(): Message {
  return {
    id: genId(),
    role: 'assistant',
    content: '',
    thinkContent: '',
    thinkDone: false,
    toolCalls: [],
    timestamp: new Date(),
  }
}

// 取出最后一条 assistant 消息，若不存在则创建一条后追加
function ensureLastAssistant(msgs: Message[]): Message[] {
  const last = msgs[msgs.length - 1]
  if (last && last.role === 'assistant') return msgs
  return [...msgs, emptyAssistantMessage()]
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isStreaming: false,
  threadId: localStorage.getItem('everloop_thread_id') || null,
  currentModel: 'qwen2.5-72b',
  availableModels: [],
  totalTokensUsed: 0,
  loopStatus: [],
  statusTimeline: [],
  usageSummary: {
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    cacheCreationTokens: 0,
    estimatedCostUsd: 0,
  },

  appendTextChunk: (chunk) => {
    set((state) => {
      const msgs = ensureLastAssistant([...state.messages])
      const last = msgs[msgs.length - 1]
      msgs[msgs.length - 1] = { ...last, content: last.content + chunk }
      return {
        messages: msgs,
        totalTokensUsed: state.totalTokensUsed + estimateTokens(chunk),
      }
    })
  },

  replaceText: (content) => {
    set((state) => {
      const msgs = ensureLastAssistant([...state.messages])
      const last = msgs[msgs.length - 1]
      msgs[msgs.length - 1] = { ...last, content }
      return { messages: msgs }
    })
  },

  appendThinkChunk: (chunk) => {
    set((state) => {
      const msgs = ensureLastAssistant([...state.messages])
      const last = msgs[msgs.length - 1]
      msgs[msgs.length - 1] = { ...last, thinkContent: last.thinkContent + chunk }
      return { messages: msgs }
    })
  },

  markThinkDone: () => {
    set((state) => {
      const msgs = [...state.messages]
      const last = msgs[msgs.length - 1]
      if (last && last.role === 'assistant') {
        msgs[msgs.length - 1] = { ...last, thinkDone: true }
      }
      return { messages: msgs }
    })
  },

  addToolCallToMessage: (entry) => {
    set((state) => {
      const msgs = ensureLastAssistant([...state.messages])
      const last = msgs[msgs.length - 1]
      msgs[msgs.length - 1] = {
        ...last,
        toolCalls: [...last.toolCalls, entry],
      }
      return { messages: msgs }
    })
  },

  updateToolCallInMessage: (id, updates) => {
    set((state) => {
      const msgs = [...state.messages]
      const last = msgs[msgs.length - 1]
      if (last && last.role === 'assistant') {
        msgs[msgs.length - 1] = {
          ...last,
          toolCalls: last.toolCalls.map((tc) =>
            tc.id === id ? { ...tc, ...updates } : tc
          ),
        }
      }
      return { messages: msgs }
    })
  },

  addUserMessage: (content) => {
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: genId(),
          role: 'user',
          content,
          thinkContent: '',
          thinkDone: false,
          toolCalls: [],
          timestamp: new Date(),
        },
      ],
      isStreaming: true,
      totalTokensUsed: state.totalTokensUsed + estimateTokens(content),
    }))
  },

  finishStream: () => set({ isStreaming: false }),

  setThreadId: (id) => {
    localStorage.setItem('everloop_thread_id', id)
    set({ threadId: id })
  },

  setCurrentModel: (model) => set({ currentModel: model }),
  setAvailableModels: (models) => set({ availableModels: models }),

  clearMessages: () => {
    localStorage.removeItem('everloop_thread_id')
    set({
      messages: [],
      threadId: null,
      totalTokensUsed: 0,
      loopStatus: [],
      statusTimeline: [],
      usageSummary: {
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheCreationTokens: 0,
        estimatedCostUsd: 0,
      },
    })
  },

  addTokensUsed: (count) =>
    set((state) => ({ totalTokensUsed: state.totalTokensUsed + count })),

  addLoopStatus: (event) => {
    set((state) => ({
      loopStatus: [
        ...state.loopStatus,
        {
          id: `loop-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
          phase: event.phase,
          message: event.message,
          status: event.status,
          timestamp: new Date(),
        },
      ].slice(-40),
    }))
  },

  pushStatusTimeline: (event) => {
    set((state) => ({
      statusTimeline: [
        ...state.statusTimeline,
        {
          id: `st-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
          seq: state.statusTimeline.length + 1,
          kind: event.kind,
          status: event.status,
          phase: event.phase,
          message: event.message,
          toolCallId: event.toolCallId,
          timestamp: new Date(),
        },
      ].slice(-200),
    }))
  },

  finalizeRunningToolCalls: (finalStatus = 'done') => {
    set((state) => {
      const msgs = [...state.messages]
      const last = msgs[msgs.length - 1]
      if (last && last.role === 'assistant') {
        msgs[msgs.length - 1] = {
          ...last,
          toolCalls: last.toolCalls.map((tc) =>
            tc.status === 'running'
              ? {
                  ...tc,
                  status: finalStatus,
                  resultPreview: tc.resultPreview || (finalStatus === 'error' ? '[中断/异常结束]' : '[已结束]'),
                }
              : tc,
          ),
        }
      }
      return { messages: msgs }
    })
  },

  setUsageSummary: (usage) => {
    set((state) => ({
      usageSummary: {
        ...state.usageSummary,
        ...usage,
      },
    }))
  },

  clearLoopState: () => {
    set({
      loopStatus: [],
      statusTimeline: [],
      usageSummary: {
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheCreationTokens: 0,
        estimatedCostUsd: 0,
      },
    })
  },
}))
