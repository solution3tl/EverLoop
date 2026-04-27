import { useMemo, useState } from 'react'
import { useChatStore } from '../store/chatStore'

const STEP_ORDER = ['理解问题', '检索信息', '分析输入', '组织答案'] as const

function mapPhaseToStep(phase: string): (typeof STEP_ORDER)[number] {
  const p = phase.toLowerCase()
  if (p.includes('compact') || p.includes('transition') || p.includes('plan')) return '理解问题'
  if (p.includes('tool') || p.includes('observation')) return '检索信息'
  if (p.includes('llm') || p.includes('think')) return '分析输入'
  if (p.includes('control')) return '组织答案'
  return '理解问题'
}

export function AIStatusPanel() {
  const [expanded, setExpanded] = useState(false)
  const timeline = useChatStore((s) => s.statusTimeline)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const usage = useChatStore((s) => s.usageSummary)

  const recent = useMemo(() => timeline.slice(-16), [timeline])

  const stepState = useMemo(() => {
    const state: Record<(typeof STEP_ORDER)[number], 'pending' | 'running' | 'done' | 'error'> = {
      理解问题: 'pending',
      检索信息: 'pending',
      分析输入: 'pending',
      组织答案: 'pending',
    }

    for (const ev of timeline) {
      const step = mapPhaseToStep(ev.phase)
      if (ev.status === 'error') {
        state[step] = 'error'
      } else if (ev.status === 'running') {
        if (state[step] !== 'done') state[step] = 'running'
      } else if (ev.status === 'done') {
        state[step] = 'done'
      }
    }

    if (!isStreaming && timeline.length > 0 && state['组织答案'] === 'pending') {
      state['组织答案'] = 'done'
    }

    return state
  }, [timeline, isStreaming])

  const headline = useMemo(() => {
    if (recent.length === 0) return isStreaming ? '系统正在处理请求...' : '等待你的下一条消息'
    const last = recent[recent.length - 1]
    return last.message || `${last.phase} ${last.status}`
  }, [recent, isStreaming])

  if (!isStreaming && recent.length === 0) return null

  return (
    <div className="ai-status-panel">
      <button className="ai-status-head" onClick={() => setExpanded((v) => !v)}>
        <span className={`tiny-dot ${isStreaming ? 'breathing' : ''}`} />
        <span className="ai-status-title">AI 思考状态</span>
        <span className="ai-status-headline">{headline}</span>
        <em>{expanded ? '收起' : '展开'}</em>
      </button>

      <div className="ai-status-steps">
        {STEP_ORDER.map((step) => (
          <div key={step} className={`ai-step ${stepState[step]}`}>
            <span className="ai-step-dot" />
            <span>{step}</span>
          </div>
        ))}
      </div>

      {expanded && (
        <div className="ai-status-body">
          <div className="ai-status-events">
            {recent.map((ev) => (
              <div key={ev.id} className={`ai-event ${ev.status}`}>
                <span className="event-phase">{ev.phase}</span>
                <span className="event-message">{ev.message}</span>
              </div>
            ))}
          </div>
          <div className="ai-status-usage">
            in {usage.inputTokens} / out {usage.outputTokens} / cost ${usage.estimatedCostUsd.toFixed(4)}
          </div>
        </div>
      )}
    </div>
  )
}
