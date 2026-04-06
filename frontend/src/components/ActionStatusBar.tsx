import React from 'react'
import { useChatStore } from '../store/chatStore'

export function ActionStatusBar() {
  // 修复问题 #4/#12: 展示完整工具调用历史列表，而不是只显示当前状态
  const toolCallHistory = useChatStore((s) => s.toolCallHistory)
  const currentActionStatus = useChatStore((s) => s.currentActionStatus)

  if (toolCallHistory.length === 0 && !currentActionStatus) return null

  return (
    <div
      style={{
        padding: '8px 12px',
        background: 'rgba(99, 102, 241, 0.08)',
        border: '1px solid rgba(99, 102, 241, 0.2)',
        borderRadius: '10px',
        margin: '8px 0 4px 42px',
        fontSize: '12px',
        maxWidth: '70%',
      }}
    >
      {toolCallHistory.map((entry) => (
        <div
          key={entry.id}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '2px',
            padding: '4px 0',
            borderBottom: '1px solid rgba(255,255,255,0.05)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {/* 状态图标 */}
            {entry.status === 'running' ? (
              <span
                style={{
                  display: 'inline-block',
                  width: '7px',
                  height: '7px',
                  borderRadius: '50%',
                  background: '#6366f1',
                  animation: 'pulse 1.5s ease-in-out infinite',
                  flexShrink: 0,
                }}
              />
            ) : (
              <span style={{ color: '#34d399', flexShrink: 0, fontSize: '11px' }}>✓</span>
            )}
            <span style={{ color: '#a5b4fc', fontWeight: 500 }}>{entry.message}</span>
          </div>
          {/* 工具返回结果预览 */}
          {entry.result && (
            <div
              style={{
                marginLeft: '13px',
                color: '#6b7280',
                fontSize: '11px',
                fontFamily: 'monospace',
                maxHeight: '60px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              → {entry.result}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
