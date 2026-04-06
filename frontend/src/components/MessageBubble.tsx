import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import { Message, ToolCallEntry } from '../store/chatStore'

interface Props {
  message: Message
  isStreaming?: boolean
}

// ── 思考折叠框 ────────────────────────────────────────────────────
function ThinkBlock({
  content,
  done,
  isStreaming,
}: {
  content: string
  done: boolean
  isStreaming: boolean
}) {
  // 正在思考时默认展开；思考完成后默认折叠
  const [expanded, setExpanded] = useState(!done)

  // 思考刚完成时自动折叠
  React.useEffect(() => {
    if (done) setExpanded(false)
  }, [done])

  if (!content) return null

  return (
    <div
      style={{
        marginBottom: '10px',
        borderRadius: '8px',
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,0.07)',
        background: 'rgba(255,255,255,0.03)',
      }}
    >
      {/* 头部：点击展开/折叠 */}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 10px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: '#6b7280',
          fontSize: '11px',
          textAlign: 'left',
        }}
      >
        {/* 呼吸灯：仅在思考中显示 */}
        {!done && isStreaming && (
          <span
            style={{
              display: 'inline-block',
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: '#818cf8',
              animation: 'breathe 1.8s ease-in-out infinite',
              flexShrink: 0,
            }}
          />
        )}
        {done && (
          <span style={{ color: '#4b5563', fontSize: '10px' }}>✦</span>
        )}
        <span style={{ flex: 1, color: done ? '#4b5563' : '#818cf8' }}>
          {done ? '已深度思考' : '正在思考...'}
        </span>
        <span style={{ color: '#374151', fontSize: '10px' }}>
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* 内容区 */}
      {expanded && (
        <div
          style={{
            padding: '4px 10px 10px',
            fontSize: '12px',
            lineHeight: '1.6',
            color: '#4b5563',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: '300px',
            overflowY: 'auto',
            borderTop: '1px solid rgba(255,255,255,0.05)',
          }}
        >
          {content}
          {/* 打字机光标：思考进行中 */}
          {!done && isStreaming && (
            <span
              style={{
                display: 'inline-block',
                width: '6px',
                height: '12px',
                background: '#6366f1',
                borderRadius: '1px',
                marginLeft: '2px',
                animation: 'blink 1s step-end infinite',
                verticalAlign: 'text-bottom',
              }}
            />
          )}
        </div>
      )}
    </div>
  )
}

// ── 工具调用卡片 ─────────────────────────────────────────────────
function ToolCallCard({ entry }: { entry: ToolCallEntry }) {
  const [expanded, setExpanded] = useState(false)
  const argsStr = Object.keys(entry.toolArgs).length
    ? JSON.stringify(entry.toolArgs, null, 2)
    : ''

  return (
    <div
      style={{
        marginBottom: '6px',
        borderRadius: '7px',
        border: '1px solid rgba(99,102,241,0.2)',
        background: 'rgba(99,102,241,0.05)',
        fontSize: '12px',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '7px',
          padding: '6px 10px',
          cursor: argsStr || entry.resultPreview ? 'pointer' : 'default',
        }}
        onClick={() => (argsStr || entry.resultPreview) && setExpanded((v) => !v)}
      >
        {/* 状态指示 */}
        {entry.status === 'running' ? (
          <span
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: '#818cf8',
              animation: 'breathe 1.8s ease-in-out infinite',
              flexShrink: 0,
            }}
          />
        ) : (
          <span style={{ color: '#34d399', fontSize: '11px', flexShrink: 0 }}>✓</span>
        )}

        {/* 工具名 */}
        <span style={{ color: '#a5b4fc', fontWeight: 500, fontFamily: 'monospace' }}>
          {entry.toolName}
        </span>

        {/* 状态文字 */}
        <span style={{ color: '#4b5563', flex: 1 }}>
          {entry.status === 'running' ? '调用中...' : '完成'}
        </span>

        {/* 展开箭头 */}
        {(argsStr || entry.resultPreview) && (
          <span style={{ color: '#374151', fontSize: '10px' }}>
            {expanded ? '▲' : '▼'}
          </span>
        )}
      </div>

      {/* 展开详情 */}
      {expanded && (
        <div
          style={{
            borderTop: '1px solid rgba(99,102,241,0.1)',
            padding: '6px 10px',
          }}
        >
          {argsStr && (
            <div style={{ marginBottom: entry.resultPreview ? '6px' : 0 }}>
              <div style={{ color: '#6b7280', fontSize: '11px', marginBottom: '2px' }}>
                参数
              </div>
              <pre
                style={{
                  margin: 0,
                  color: '#9ca3af',
                  fontSize: '11px',
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: '80px',
                  overflowY: 'auto',
                }}
              >
                {argsStr}
              </pre>
            </div>
          )}
          {entry.resultPreview && (
            <div>
              <div style={{ color: '#6b7280', fontSize: '11px', marginBottom: '2px' }}>
                结果预览
              </div>
              <div
                style={{
                  color: '#6b7280',
                  fontSize: '11px',
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: '60px',
                  overflowY: 'auto',
                }}
              >
                {entry.resultPreview}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Markdown 渲染配置 ────────────────────────────────────────────
const mdComponents = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p style={{ margin: '4px 0' }}>{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol style={{ paddingLeft: '20px', margin: '8px 0' }}>{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li style={{ margin: '2px 0' }}>{children}</li>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 style={{ fontSize: '1.4em', margin: '12px 0 6px', color: '#a5b4fc' }}>{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 style={{ fontSize: '1.2em', margin: '10px 0 4px', color: '#a5b4fc' }}>{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 style={{ fontSize: '1.1em', margin: '8px 0 4px', color: '#c4b5fd' }}>{children}</h3>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote
      style={{
        borderLeft: '3px solid #6366f1',
        paddingLeft: '12px',
        margin: '8px 0',
        color: '#9ca3af',
        fontStyle: 'italic',
      }}
    >
      {children}
    </blockquote>
  ),
  table: ({ children }: { children?: React.ReactNode }) => (
    <div style={{ overflowX: 'auto', margin: '8px 0' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '13px' }}>
        {children}
      </table>
    </div>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th
      style={{
        padding: '6px 12px',
        background: 'rgba(99,102,241,0.2)',
        border: '1px solid rgba(255,255,255,0.1)',
        textAlign: 'left',
      }}
    >
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td style={{ padding: '6px 12px', border: '1px solid rgba(255,255,255,0.08)' }}>
      {children}
    </td>
  ),
}

// ── 主组件 ───────────────────────────────────────────────────────
export function MessageBubble({ message, isStreaming = false }: Props) {
  const isUser = message.role === 'user'

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: '16px',
        animation: 'fadeIn 0.2s ease',
      }}
    >
      {/* AI 头像 */}
      {!isUser && (
        <div
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '14px',
            flexShrink: 0,
            marginRight: '10px',
            marginTop: '4px',
          }}
        >
          🤖
        </div>
      )}

      <div style={{ maxWidth: '75%', minWidth: 0 }}>
        {/* ── 思考折叠框（仅 assistant） */}
        {!isUser && message.thinkContent && (
          <ThinkBlock
            content={message.thinkContent}
            done={message.thinkDone}
            isStreaming={isStreaming}
          />
        )}

        {/* ── 工具调用卡片列表（仅 assistant） */}
        {!isUser && message.toolCalls.length > 0 && (
          <div style={{ marginBottom: '8px' }}>
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} entry={tc} />
            ))}
          </div>
        )}

        {/* ── 正文气泡 */}
        {(isUser || message.content || (!message.thinkContent && !message.toolCalls.length)) && (
          <div
            style={{
              padding: isUser ? '10px 16px' : '12px 16px',
              borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
              background: isUser
                ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                : 'rgba(255,255,255,0.06)',
              border: isUser ? 'none' : '1px solid rgba(255,255,255,0.08)',
              color: '#e8e8ed',
              fontSize: '14px',
              lineHeight: '1.6',
              wordBreak: 'break-word',
            }}
          >
            {message.content === '' && !isUser ? (
              // 等待首字节时的光标
              <span
                style={{
                  display: 'inline-block',
                  width: '10px',
                  height: '14px',
                  background: '#6366f1',
                  borderRadius: '2px',
                  animation: 'blink 1s step-end infinite',
                }}
              />
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

      {/* 用户头像 */}
      {isUser && (
        <div
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #3b82f6, #06b6d4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '14px',
            flexShrink: 0,
            marginLeft: '10px',
            marginTop: '4px',
          }}
        >
          👤
        </div>
      )}
    </div>
  )
}
