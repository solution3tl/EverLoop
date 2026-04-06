import React, { useState, useEffect } from 'react'
import { LoginPage } from './components/LoginPage'
import { ChatWindow } from './components/ChatWindow'
import { useChatStore } from './store/chatStore'
import { fetchModels } from './hooks/useSSEStream'

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [username, setUsername] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // 修复问题 #15: 用 hook 订阅 availableModels，而不是在渲染时用 getState() 快照读取
  const { setAvailableModels, setCurrentModel, currentModel, clearMessages, availableModels } = useChatStore()

  // 检查本地 Token
  useEffect(() => {
    const token = localStorage.getItem('everloop_token')
    const storedUsername = localStorage.getItem('everloop_username')
    if (token) {
      setIsLoggedIn(true)
      setUsername(storedUsername || 'User')
    }
  }, [])

  // 加载模型列表
  useEffect(() => {
    if (isLoggedIn) {
      fetchModels().then((data) => {
        if (data.models?.length) {
          setAvailableModels(data.models)
          if (data.default) setCurrentModel(data.default)
        }
      })
    }
  }, [isLoggedIn])

  const handleLogin = (_token: string, name: string) => {
    setIsLoggedIn(true)
    setUsername(name)
  }

  const handleLogout = () => {
    localStorage.removeItem('everloop_token')
    localStorage.removeItem('everloop_username')
    setIsLoggedIn(false)
    clearMessages()
  }

  if (!isLoggedIn) {
    return <LoginPage onLogin={handleLogin} />
  }

  // 修复问题 #15: 删除 useChatStore.getState() 调用（已在上面通过 hook 获取 availableModels）

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部导航 */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 20px',
          background: 'rgba(255,255,255,0.03)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          flexShrink: 0,
        }}
      >
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '24px' }}>🌀</span>
          <span
            style={{
              fontSize: '18px',
              fontWeight: '700',
              background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            EverLoop
          </span>
        </div>

        {/* 中间：模型选择 + 新对话 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {availableModels.length > 0 && (
            <select
              value={currentModel}
              onChange={(e) => setCurrentModel(e.target.value)}
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '8px',
                color: '#e8e8ed',
                padding: '6px 10px',
                fontSize: '13px',
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              {availableModels.map((m) => (
                <option key={m} value={m} style={{ background: '#1a1a24' }}>
                  {m}
                </option>
              ))}
            </select>
          )}

          <button
            onClick={() => clearMessages()}
            title="新对话"
            style={{
              padding: '6px 12px',
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: '8px',
              color: '#9ca3af',
              fontSize: '13px',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
            onMouseEnter={(e) => {
              ;(e.target as HTMLButtonElement).style.color = '#e8e8ed'
            }}
            onMouseLeave={(e) => {
              ;(e.target as HTMLButtonElement).style.color = '#9ca3af'
            }}
          >
            ✦ 新对话
          </button>
        </div>

        {/* 用户信息 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '13px', color: '#6b7280' }}>
            👤 {username}
          </span>
          <button
            onClick={handleLogout}
            style={{
              padding: '6px 12px',
              background: 'transparent',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px',
              color: '#6b7280',
              fontSize: '13px',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
            onMouseEnter={(e) => {
              ;(e.target as HTMLButtonElement).style.color = '#f87171'
              ;(e.target as HTMLButtonElement).style.borderColor = 'rgba(239,68,68,0.4)'
            }}
            onMouseLeave={(e) => {
              ;(e.target as HTMLButtonElement).style.color = '#6b7280'
              ;(e.target as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.1)'
            }}
          >
            退出
          </button>
        </div>
      </header>

      {/* 聊天主体 */}
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
        <ChatWindow />
      </main>

      {/* CSS 动画注入 */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.8); }
        }
        @keyframes dotPulse {
          0%, 100% { opacity: 0.3; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.2); }
        }
        @keyframes breathe {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.3; transform: scale(0.7); }
        }
        select option {
          background: #1a1a24;
          color: #e8e8ed;
        }
      `}</style>
    </div>
  )
}
