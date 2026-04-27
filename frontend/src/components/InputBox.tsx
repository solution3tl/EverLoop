import { useCallback, useRef, useState } from 'react'
import { useChatStore } from '../store/chatStore'
import { useSSEStream } from '../hooks/useSSEStream'

const modes = ['对话', '任务', '调研', '代码', '自治']

export function InputBox() {
  const [text, setText] = useState('')
  const [mode, setMode] = useState('任务')
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
    await sendMessage({ message: `[${mode}] ${msg}`, threadId, modelName: currentModel })
  }, [text, isStreaming, threadId, currentModel, sendMessage, mode])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 220)}px`
  }

  return (
    <div className="composer-shell">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={handleTextareaChange}
        onKeyDown={handleKeyDown}
        placeholder={
          isStreaming
            ? '智能体回复中，你可以提前输入下一条任务...'
            : '请告诉你的智能体要做什么...'
        }
        rows={1}
        className="composer-input"
      />

      <div className="composer-toolbar">
        <div className="composer-actions">
          <button className="chip">附件</button>
          <button className="chip">工具</button>
          <select value={mode} onChange={(e) => setMode(e.target.value)} className="chip mode-select">
            {modes.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>

        {isStreaming ? (
          <button className="send-btn stop" onClick={abort}>
            停止生成
          </button>
        ) : (
          <button className="send-btn" onClick={handleSend} disabled={!text.trim()}>
            发送
          </button>
        )}
      </div>
    </div>
  )
}
