import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import { Message, ToolCallEntry } from '../store/chatStore'

interface Props {
  message: Message
  isStreaming?: boolean
}

function ThinkBlock({
  content,
  done,
  isStreaming,
}: {
  content: string
  done: boolean
  isStreaming: boolean
}) {
  const [expanded, setExpanded] = useState(!done)

  useEffect(() => {
    if (done) setExpanded(false)
  }, [done])

  if (!content) return null

  return (
    <div className="think-block">
      <button className="think-head" onClick={() => setExpanded((v) => !v)}>
        <span className={`tiny-dot ${!done && isStreaming ? 'breathing' : ''}`} />
        <span>{done ? '思考摘要已生成' : '智能体正在思考...'}</span>
        <em>{expanded ? '▲' : '▼'}</em>
      </button>
      {expanded && (
        <div className="think-body">
          {content}
          {!done && isStreaming && <span className="blinking-caret" />}
        </div>
      )}
    </div>
  )
}

function iconForTool(name: string): string {
  const value = name.toLowerCase()
  if (value.includes('search') || value.includes('browser')) return '🔎'
  if (value.includes('code') || value.includes('python')) return '</>'
  if (value.includes('db') || value.includes('sql')) return '⛁'
  if (value.includes('file') || value.includes('read')) return '📄'
  if (value.includes('api')) return '⚡'
  return '🔧'
}

function ToolCallCard({ entry }: { entry: ToolCallEntry }) {
  const [expanded, setExpanded] = useState(false)
  const argsStr = Object.keys(entry.toolArgs).length ? JSON.stringify(entry.toolArgs, null, 2) : ''
  const statusText = entry.status === 'done' ? '已完成' : entry.status === 'error' ? '异常' : '进行中'

  return (
    <div className="tool-card">
      <button className="tool-head" onClick={() => setExpanded((v) => !v)}>
        <span className="tool-icon">{iconForTool(entry.toolName)}</span>
        <div>
          <strong>{entry.toolName}</strong>
          <span>使用内部工具链</span>
        </div>
        <em className={entry.status}>{statusText}</em>
      </button>

      {expanded && (
        <div className="tool-body">
          {argsStr && (
            <div>
              <label>参数</label>
              <pre>{argsStr}</pre>
            </div>
          )}
          {entry.resultPreview && (
            <div>
              <label>结果</label>
              <p>{entry.resultPreview}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const mdComponents = {
  p: ({ children }: { children?: React.ReactNode }) => <p style={{ margin: '6px 0' }}>{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>{children}</ul>
  ),
  li: ({ children }: { children?: React.ReactNode }) => <li style={{ margin: '2px 0' }}>{children}</li>,
}

export function MessageBubble({ message, isStreaming = false }: Props) {
  const isUser = message.role === 'user'

  return (
    <div className={`message-row ${isUser ? 'user' : 'assistant'}`}>
      {!isUser && <div className="agent-avatar">助手</div>}

      <div className="message-stack">
        {!isUser && message.thinkContent && (
          <ThinkBlock content={message.thinkContent} done={message.thinkDone} isStreaming={isStreaming} />
        )}

        {!isUser && message.toolCalls.length > 0 && (
          <div className="tool-call-list">
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} entry={tc} />
            ))}
          </div>
        )}

        {(isUser || message.content || (!message.thinkContent && !message.toolCalls.length)) && (
          <div className={`message-bubble ${isUser ? 'user' : 'assistant'}`}>
            {message.content === '' && !isUser ? (
              <span className="blinking-caret" />
            ) : isUser ? (
              <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={mdComponents}
              >
                {message.content}
              </ReactMarkdown>
            )}
          </div>
        )}
      </div>

      {isUser && <div className="user-avatar">你</div>}
    </div>
  )
}
