import { useEffect, useRef } from 'react'
import { useChatStore } from '../store/chatStore'
import { MessageBubble } from './MessageBubble'
import { InputBox } from './InputBox'
import { AIStatusPanel } from './AIStatusPanel'

interface ChatWindowProps {
  title: string
  description: string
  onToggleRightPanel: () => void
}

const suggestionCards = [
  { title: '分析业务指标', desc: '找出趋势并解释关键变化。' },
  { title: '调研市场', desc: '比较竞品并识别机会点。' },
  { title: '总结文档', desc: '快速阅读文件并提炼结论。' },
  { title: '编写与审查代码', desc: '生成代码并定位潜在问题。' },
  { title: '创建项目计划', desc: '将目标拆解为可执行步骤。' },
  { title: '生成分析报告', desc: '输出结构化结论与建议。' },
]

export function ChatWindow({ title, description, onToggleRightPanel }: ChatWindowProps) {
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const threadId = useChatStore((s) => s.threadId)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  return (
    <div className="chat-window">
      <div className="chat-header">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <div className="chat-header-actions">
          <button>分享</button>
          <button>导出</button>
          <button>更多</button>
          <button onClick={onToggleRightPanel}>切换右侧面板</button>
        </div>
      </div>

      <AIStatusPanel />
      <div className="message-timeline">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="empty-logo">EL</div>
            <h3>你希望智能体帮你做什么？</h3>
            <p>
              从任务、问题或工作流开始。你的智能体可以调研、分析、写作、编程并生成可交付成果。
            </p>
            <div className="suggestion-grid">
              {suggestionCards.map((item) => (
                <button key={item.title} className="suggestion-card">
                  <strong>{item.title}</strong>
                  <span>{item.desc}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.length > 0 && (
          <div className="thread-id">执行进度由上方 AI 思考状态面板实时展示</div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isStreaming={isStreaming && idx === messages.length - 1 && msg.role === 'assistant'}
          />
        ))}

        {isStreaming && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
          <div className="thinking-banner">
            <span className="pulse-dot" />
            <span>系统正在处理你的请求...</span>
          </div>
        )}

        {threadId && <div className="thread-id">线程：{threadId}</div>}
        <div ref={bottomRef} />
      </div>

      <InputBox />
    </div>
  )
}
