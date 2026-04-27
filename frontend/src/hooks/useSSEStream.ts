import { useRef, useCallback } from 'react'
import { useChatStore } from '../store/chatStore'

const envApiBase = ((import.meta as any).env?.VITE_API_BASE || '').replace(/\/$/, '')
const API_BASES = [
  ...(envApiBase ? [envApiBase] : []),
  '/api',
  'http://127.0.0.1:8001/api',
  'http://localhost:8001/api',
]

function getToken(): string {
  return localStorage.getItem('everloop_token') || ''
}

interface SendMessageOptions {
  message: string
  threadId?: string | null
  modelName?: string
}

const MAX_RETRIES = 3

function buildApiUrl(base: string, path: string): string {
  return `${base}${path}`
}

function clearAuthAndNotify() {
  localStorage.removeItem('everloop_token')
  localStorage.removeItem('everloop_username')
  localStorage.removeItem('everloop_thread_id')
  window.dispatchEvent(new CustomEvent('everloop-auth-expired'))
}

async function fetchWithFallback(
  path: string,
  init: RequestInit,
  preferredBase?: string,
): Promise<{ response: Response; base: string }> {
  const bases = preferredBase
    ? [preferredBase, ...API_BASES.filter((b) => b !== preferredBase)]
    : [...API_BASES]

  let lastError: unknown = null

  for (const base of bases) {
    try {
      const response = await fetch(buildApiUrl(base, path), init)
      return { response, base }
    } catch (err) {
      lastError = err
    }
  }

  throw lastError instanceof Error ? lastError : new Error('请求失败')
}

export function useSSEStream() {
  const abortControllerRef = useRef<AbortController | null>(null)
  const didFinishRef = useRef(false)
  const toolIdCounter = useRef(0)
  const preferredApiBaseRef = useRef<string | null>(null)

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
    addLoopStatus,
    setUsageSummary,
    clearLoopState,
    pushStatusTimeline,
    finalizeRunningToolCalls,
  } = useChatStore()

  const finalizeStream = useCallback(
    (reason: 'done' | 'error' | 'abort') => {
      markThinkDone()
      finalizeRunningToolCalls(reason === 'error' ? 'error' : 'done')
      if (!didFinishRef.current) {
        didFinishRef.current = true
        finishStream()
      }
    },
    [finishStream, finalizeRunningToolCalls, markThinkDone],
  )

  const abort = useCallback(() => {
    abortControllerRef.current?.abort()
    finalizeStream('abort')
  }, [finalizeStream])

  const sendMessage = useCallback(
    async ({ message, threadId, modelName }: SendMessageOptions) => {
      didFinishRef.current = false
      toolIdCounter.current = 0
      addUserMessage(message)
      clearLoopState()

      let retryCount = 0
      let retryDelay = 1000

      const attempt = async (): Promise<void> => {
        abortControllerRef.current = new AbortController()

        try {
          const { response, base } = await fetchWithFallback(
            '/chat/stream',
            {
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
            },
            preferredApiBaseRef.current ?? undefined,
          )

          preferredApiBaseRef.current = base

          if (!response.ok) {
            if (response.status === 401) {
              throw new Error('__AUTH_401__')
            }
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
          }

          const newThreadId = response.headers.get('X-Thread-Id')
          if (newThreadId) setThreadId(newThreadId)

          const reader = response.body?.getReader()
          if (!reader) throw new Error('无法获取响应流')

          const decoder = new TextDecoder()
          let buffer = ''

          while (true) {
            const { done, value } = await reader.read()
            if (done) {
              finalizeStream('done')
              break
            }

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
                  case 'text':
                    if (packet.content) {
                      appendTextChunk(packet.content)
                      pushStatusTimeline({
                        kind: 'llm',
                        status: 'running',
                        phase: 'llm',
                        message: packet.content.slice(0, 80),
                      })
                    }
                    break

                  case 'text_replace':
                    replaceText(packet.content ?? '')
                    pushStatusTimeline({
                      kind: 'llm',
                      status: 'running',
                      phase: 'llm',
                      message: '替换当前回答文本',
                    })
                    break

                  case 'think':
                    if (packet.content) {
                      appendThinkChunk(packet.content)
                      pushStatusTimeline({
                        kind: 'llm',
                        status: 'running',
                        phase: 'think',
                        message: packet.content.slice(0, 80),
                      })
                    }
                    break

                  case 'think_end':
                    markThinkDone()
                    pushStatusTimeline({
                      kind: 'llm',
                      status: 'done',
                      phase: 'think',
                      message: '思考阶段结束',
                    })
                    break

                  case 'tool_call_start': {
                    const id = packet.tool_call_id || `tool-${++toolIdCounter.current}`
                    addToolCallToMessage({
                      id,
                      toolName: packet.tool_name || '工具调用',
                      toolArgs: packet.tool_args || {},
                      status: 'running',
                    })
                    pushStatusTimeline({
                      kind: 'tool',
                      status: 'running',
                      phase: 'tool',
                      message: `调用 ${packet.tool_name || 'tool'}`,
                      toolCallId: id,
                    })
                    break
                  }

                  case 'tool_call_done': {
                    const doneId = packet.tool_call_id || ''
                    if (doneId) {
                      updateToolCallInMessage(doneId, {
                        status: 'done',
                        resultPreview: packet.result_preview,
                      })
                    }
                    pushStatusTimeline({
                      kind: 'tool',
                      status: 'done',
                      phase: 'tool',
                      message: `${packet.tool_name || 'tool'} 完成`,
                      toolCallId: doneId || undefined,
                    })
                    break
                  }

                  case 'custom_status': {
                    const status = packet.status === 'completed' ? 'done' : packet.status === 'error' ? 'error' : 'running'
                    addLoopStatus({
                      phase: 'status',
                      status,
                      message: packet.message || '',
                    })
                    pushStatusTimeline({
                      kind: 'phase',
                      status,
                      phase: 'status',
                      message: packet.message || '',
                    })
                    break
                  }

                  case 'loop_status':
                    addLoopStatus({
                      phase: packet.phase || 'unknown',
                      status: packet.status || 'running',
                      message: packet.message || '',
                    })
                    pushStatusTimeline({
                      kind: 'phase',
                      status: packet.status || 'running',
                      phase: packet.phase || 'unknown',
                      message: packet.message || '',
                    })
                    break

                  case 'usage_update':
                    if (packet.usage) {
                      setUsageSummary({
                        inputTokens: packet.usage.input_tokens ?? 0,
                        outputTokens: packet.usage.output_tokens ?? 0,
                        cacheReadTokens: packet.usage.cache_read_input_tokens ?? 0,
                        cacheCreationTokens: packet.usage.cache_creation_input_tokens ?? 0,
                        estimatedCostUsd: packet.usage.estimated_cost_usd ?? 0,
                      })
                    }
                    break

                  case 'observation':
                    addLoopStatus({
                      phase: 'observation',
                      status: packet.is_error ? 'error' : 'done',
                      message: `${packet.tool_name || 'tool'} -> ${packet.content_preview || ''}`,
                    })
                    pushStatusTimeline({
                      kind: 'observation',
                      status: packet.is_error ? 'error' : 'done',
                      phase: 'observation',
                      message: `${packet.tool_name || 'tool'} -> ${packet.content_preview || ''}`,
                      toolCallId: packet.tool_use_id || undefined,
                    })
                    break

                  case 'control': {
                    const cstatus = packet.status === 'error' ? 'error' : packet.status === 'abort' ? 'error' : 'done'
                    pushStatusTimeline({
                      kind: 'control',
                      status: cstatus,
                      phase: 'control',
                      message: `流结束: ${packet.status || 'done'}`,
                    })
                    if (packet.status === 'done') {
                      finalizeStream('done')
                    } else if (packet.status === 'abort') {
                      finalizeStream('abort')
                    } else if (packet.status === 'error') {
                      appendTextChunk('\n\n[服务异常，请重试]')
                      finalizeStream('error')
                    }
                    break
                  }

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
            finalizeStream('abort')
            return
          }

          const isAuthError = err instanceof Error && err.message === '__AUTH_401__'
          if (isAuthError) {
            clearAuthAndNotify()
            appendTextChunk('\n\n[登录已失效，请重新登录]')
            finalizeStream('error')
            return
          }

          if (retryCount < MAX_RETRIES) {
            retryCount++
            appendTextChunk(`\n\n[连接中断，正在重试 (${retryCount}/${MAX_RETRIES})...]`)
            await new Promise((resolve) => setTimeout(resolve, retryDelay))
            retryDelay = Math.min(retryDelay * 2, 10000)
            return attempt()
          }

          appendTextChunk(`\n\n[连接错误：${err instanceof Error ? err.message : '未知错误'}，已停止重试]`)
          finalizeStream('error')
        }
      }

      try {
        await attempt()
      } finally {
        if (!didFinishRef.current) {
          finalizeStream('done')
        }
      }
    },
    [
      addUserMessage,
      clearLoopState,
      appendTextChunk,
      replaceText,
      appendThinkChunk,
      markThinkDone,
      addToolCallToMessage,
      updateToolCallInMessage,
      addLoopStatus,
      setUsageSummary,
      setThreadId,
      pushStatusTimeline,
      finalizeRunningToolCalls,
      finalizeStream,
    ],
  )

  return { sendMessage, abort }
}

async function jsonRequestWithFallback(
  path: string,
  init: RequestInit,
  preferredBase?: string,
): Promise<{ data: any; base: string }> {
  const { response, base } = await fetchWithFallback(path, init, preferredBase)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('__AUTH_401__')
    }
    throw new Error(data.detail || `HTTP ${response.status}`)
  }
  return { data, base }
}

// 认证相关
export async function loginApi(username: string, password: string) {
  const { data } = await jsonRequestWithFallback('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return data
}

export async function registerApi(username: string, password: string) {
  const { data } = await jsonRequestWithFallback('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return data
}

export async function fetchModels() {
  try {
    const token = getToken()
    const { data } = await jsonRequestWithFallback('/chat/models', {
      method: 'GET',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    return data
  } catch (err: unknown) {
    if (err instanceof Error && err.message === '__AUTH_401__') {
      clearAuthAndNotify()
    }
    return { models: [], default: null }
  }
}
