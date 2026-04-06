import { useRef, useCallback } from 'react'
import { useChatStore } from '../store/chatStore'

const API_BASE = '/api'

function getToken(): string {
  return localStorage.getItem('everloop_token') || ''
}

interface SendMessageOptions {
  message: string
  threadId?: string | null
  modelName?: string
}

const MAX_RETRIES = 3

export function useSSEStream() {
  const abortControllerRef = useRef<AbortController | null>(null)
  const didFinishRef = useRef(false)
  // 每轮工具调用的自增 id
  const toolIdCounter = useRef(0)

  const {
    appendTextChunk,
    replaceText,
    appendThinkChunk,
    markThinkDone,
    addToolCallToMessage,
    updateToolCallInMessage,
    finishStream,
    setThreadId,
    addUserMessage,
  } = useChatStore()

  const abort = useCallback(() => {
    abortControllerRef.current?.abort()
    if (!didFinishRef.current) {
      didFinishRef.current = true
      finishStream()
    }
  }, [finishStream])

  const sendMessage = useCallback(
    async ({ message, threadId, modelName }: SendMessageOptions) => {
      didFinishRef.current = false
      toolIdCounter.current = 0
      addUserMessage(message)

      let retryCount = 0
      let retryDelay = 1000

      const attempt = async (): Promise<void> => {
        abortControllerRef.current = new AbortController()

        try {
          const response = await fetch(`${API_BASE}/chat/stream`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${getToken()}`,
            },
            body: JSON.stringify({
              message,
              thread_id: threadId || undefined,
              model_name: modelName,
            }),
            signal: abortControllerRef.current.signal,
          })

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
          }

          const newThreadId = response.headers.get('X-Thread-Id')
          if (newThreadId) setThreadId(newThreadId)

          const reader = response.body?.getReader()
          if (!reader) throw new Error('无法获取响应流')

          const decoder = new TextDecoder()
          let buffer = ''
          // 记录当前正在执行的工具调用 id（支持并行多个）
          let currentToolId: string | null = null

          while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n\n')
            buffer = lines.pop() || ''

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue
              const jsonStr = line.slice(6).trim()
              if (!jsonStr) continue

              try {
                const packet = JSON.parse(jsonStr)

                switch (packet.type) {
                  // ── 正式回答文字 ────────────────────────────────
                  case 'text':
                    if (packet.content) appendTextChunk(packet.content)
                    break

                  // 内联 tool_call 识别后整体覆盖已推出的脏内容
                  case 'text_replace':
                    replaceText(packet.content ?? '')
                    break

                  // ── 思考过程 ─────────────────────────────────────
                  case 'think':
                    if (packet.content) appendThinkChunk(packet.content)
                    break

                  case 'think_end':
                    markThinkDone()
                    break

                  // ── 工具调用 ─────────────────────────────────────
                  case 'tool_call_start': {
                    const id = `tool-${++toolIdCounter.current}`
                    currentToolId = id
                    addToolCallToMessage({
                      id,
                      toolName: packet.tool_name || '工具调用',
                      toolArgs: packet.tool_args || {},
                      status: 'running',
                    })
                    break
                  }

                  case 'tool_call_done':
                    if (currentToolId) {
                      updateToolCallInMessage(currentToolId, {
                        status: 'done',
                        resultPreview: packet.result_preview,
                      })
                      currentToolId = null
                    }
                    break

                  // ── 流程控制 ─────────────────────────────────────
                  case 'control':
                    if (packet.status === 'done' || packet.status === 'error') {
                      if (!didFinishRef.current) {
                        didFinishRef.current = true
                        finishStream()
                      }
                      if (packet.status === 'error') {
                        appendTextChunk('\n\n[服务异常，请重试]')
                      }
                    }
                    break

                  default:
                    break
                }
              } catch (_e) {
                // 忽略解析错误
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof Error && err.name === 'AbortError') {
            if (!didFinishRef.current) {
              didFinishRef.current = true
              finishStream()
            }
            return
          }

          if (retryCount < MAX_RETRIES) {
            retryCount++
            appendTextChunk(`\n\n[连接中断，正在重试 (${retryCount}/${MAX_RETRIES})...]`)
            await new Promise((resolve) => setTimeout(resolve, retryDelay))
            retryDelay = Math.min(retryDelay * 2, 10000)
            return attempt()
          } else {
            appendTextChunk(
              `\n\n[连接错误：${err instanceof Error ? err.message : '未知错误'}，已停止重试]`,
            )
            if (!didFinishRef.current) {
              didFinishRef.current = true
              finishStream()
            }
          }
        }
      }

      try {
        await attempt()
      } finally {
        if (!didFinishRef.current) {
          didFinishRef.current = true
          finishStream()
        }
      }
    },
    [
      addUserMessage,
      appendTextChunk,
      replaceText,
      appendThinkChunk,
      markThinkDone,
      addToolCallToMessage,
      updateToolCallInMessage,
      finishStream,
      setThreadId,
    ],
  )

  return { sendMessage, abort }
}

// 认证相关
export async function loginApi(username: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || '登录失败')
  }
  return res.json()
}

export async function registerApi(username: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || '注册失败')
  }
  return res.json()
}

export async function fetchModels() {
  const res = await fetch(`${API_BASE}/chat/models`)
  if (!res.ok) return { models: [], default: null }
  return res.json()
}
