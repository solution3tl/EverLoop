import React, { useEffect, useRef } from 'react'
import { useChatStore } from '../store/chatStore'
import { MessageBubble } from './MessageBubble'
import { InputBox } from './InputBox'

export function ChatWindow() {
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const threadId = useChatStore((s) => s.threadId)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* 消息列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px 16px 8px',
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              gap: '16px',
              color: '#4b5563',
            }}
          >
            <div style={{ fontSize: '48px' }}>🌀</div>
            <div style={{ fontSize: '20px', color: '#6b7280', fontWeight: '600' }}>
              EverLoop Agent
            </div>
            <div style={{ fontSize: '14px', color: '#4b5563', textAlign: 'center' }}>
              你好！我是 EverLoop，一个支持工具调用的智能助手。
              <br />
              可以问我任何问题，包括时间查询、数学计算等。
            </div>
            {threadId && (
              <div style={{ fontSize: '12px', color: '#374151' }}>
                会话 ID: {threadId}
              </div>
            )}
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isStreaming={
              isStreaming &&
              idx === messages.length - 1 &&
              msg.role === 'assistant'
            }
          />
        ))}

        {/* 等待 AI 首字节时的三点加载动画 */}
        {isStreaming &&
          messages.length > 0 &&
          messages[messages.length - 1].role === 'user' && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                marginBottom: '16px',
                color: '#6b7280',
                fontSize: '13px',
              }}
            >
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
                }}
              >
                🤖
              </div>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                {[0, 0.2, 0.4].map((delay, i) => (
                  <span
                    key={i}
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      background: '#6366f1',
                      animation: 'dotPulse 1.4s ease-in-out infinite',
                      animationDelay: `${delay}s`,
                    }}
                  />
                ))}
              </div>
            </div>
          )}

        <div ref={bottomRef} />
      </div>

      <InputBox />
    </div>
  )
}
