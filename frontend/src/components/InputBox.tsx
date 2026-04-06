import React, { useState, useRef, useCallback } from 'react'
import { useChatStore } from '../store/chatStore'
import { useSSEStream } from '../hooks/useSSEStream'

export function InputBox() {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { isStreaming, threadId, currentModel } = useChatStore()
  const { sendMessage, abort } = useSSEStream()

  const handleSend = useCallback(async () => {
    const msg = text.trim()
    if (!msg || isStreaming) return
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    await sendMessage({ message: msg, threadId, modelName: currentModel })
  }, [text, isStreaming, threadId, currentModel, sendMessage])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    // 自动调整高度
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: '10px',
        padding: '12px 16px',
        background: 'rgba(255,255,255,0.03)',
        borderTop: '1px solid rgba(255,255,255,0.08)',
      }}
    >
      <textarea
        ref={textareaRef}
        value={text}
        onChange={handleTextareaChange}
        onKeyDown={handleKeyDown}
        // 修复问题 #21: 不禁用 textarea，允许用户在 AI 回复中提前输入；只禁止发送
        disabled={false}
        placeholder={isStreaming ? 'AI 回复中，可提前输入下一个问题...' : '输入消息，Enter 发送，Shift+Enter 换行...'}
        rows={1}
        style={{
          flex: 1,
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.12)',
          borderRadius: '12px',
          padding: '10px 14px',
          color: '#e8e8ed',
          fontSize: '14px',
          resize: 'none',
          outline: 'none',
          lineHeight: '1.5',
          transition: 'border-color 0.2s',
          fontFamily: 'inherit',
          minHeight: '42px',
          maxHeight: '200px',
          opacity: isStreaming ? 0.8 : 1,
        }}
        onFocus={(e) => {
          e.target.style.borderColor = 'rgba(99,102,241,0.6)'
        }}
        onBlur={(e) => {
          e.target.style.borderColor = 'rgba(255,255,255,0.12)'
        }}
      />

      {isStreaming ? (
        <button
          onClick={abort}
          style={{
            padding: '10px 16px',
            background: 'rgba(239,68,68,0.2)',
            border: '1px solid rgba(239,68,68,0.4)',
            borderRadius: '10px',
            color: '#f87171',
            fontSize: '13px',
            cursor: 'pointer',
            whiteSpace: 'nowrap',
            transition: 'all 0.2s',
          }}
          onMouseEnter={(e) => {
            ;(e.target as HTMLButtonElement).style.background = 'rgba(239,68,68,0.35)'
          }}
          onMouseLeave={(e) => {
            ;(e.target as HTMLButtonElement).style.background = 'rgba(239,68,68,0.2)'
          }}
        >
          ⏹ 停止
        </button>
      ) : (
        <button
          onClick={handleSend}
          disabled={!text.trim()}
          style={{
            padding: '10px 20px',
            background:
              text.trim()
                ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                : 'rgba(255,255,255,0.1)',
            border: 'none',
            borderRadius: '10px',
            color: text.trim() ? '#fff' : '#666',
            fontSize: '14px',
            cursor: text.trim() ? 'pointer' : 'not-allowed',
            transition: 'all 0.2s',
            fontWeight: '500',
          }}
        >
          发送 ↑
        </button>
      )}
    </div>
  )
}
