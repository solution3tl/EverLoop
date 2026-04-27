import { useEffect, useMemo, useState } from 'react'
import { LoginPage } from './components/LoginPage'
import { ChatWindow } from './components/ChatWindow'
import { useChatStore } from './store/chatStore'
import { fetchModels } from './hooks/useSSEStream'
import {
  MCPServerItem,
  MCPToolMeta,
  SkillItem,
  callMCPTool,
  createMCPSkill,
  createMCPServer,
  fetchMCPServers,
  fetchMCPTools,
  fetchSkills,
  syncSkill,
  toggleSkill,
} from './hooks/usePlatformApi'
import platformHero from './assets/platform-hero.svg'
import mcpNetwork from './assets/mcp-network.svg'
import skillWorkbench from './assets/skill-workbench.svg'

type ViewKey = 'workspace' | 'agents' | 'mcp' | 'skills' | 'trace'
type RightTab = 'inspector' | 'activity' | 'context'

const views: Array<{ id: ViewKey; label: string; desc: string }> = [
  { id: 'workspace', label: '工作台', desc: '运行 Agent 任务' },
  { id: 'agents', label: 'Agent', desc: '能力与策略配置' },
  { id: 'mcp', label: 'MCP', desc: 'Server 与工具调试' },
  { id: 'skills', label: 'Skill', desc: '技能创建与绑定' },
  { id: 'trace', label: 'Trace', desc: '运行链路观测' },
]

function asJson(value: unknown): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [username, setUsername] = useState('')
  const [activeView, setActiveView] = useState<ViewKey>('workspace')
  const [rightTab, setRightTab] = useState<RightTab>('inspector')
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('everloop_theme')
    return saved === 'dark' ? 'dark' : 'light'
  })

  const [servers, setServers] = useState<MCPServerItem[]>([])
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [selectedServerId, setSelectedServerId] = useState<string>('')
  const [selectedTools, setSelectedTools] = useState<MCPToolMeta[]>([])
  const [toolSchemas, setToolSchemas] = useState<any[]>([])
  const [platformNotice, setPlatformNotice] = useState('')

  const {
    setAvailableModels,
    setCurrentModel,
    currentModel,
    clearMessages,
    availableModels,
    messages,
    threadId,
    isStreaming,
    statusTimeline,
    usageSummary,
  } = useChatStore()

  const selectedServer = useMemo(
    () => servers.find((server) => server.id === selectedServerId) || servers[0],
    [servers, selectedServerId],
  )

  const toolCalls = useMemo(
    () => messages.flatMap((m) => (m.role === 'assistant' ? m.toolCalls : [])),
    [messages],
  )

  const appStatusLabel = useMemo(() => {
    if (isStreaming && statusTimeline.some((t) => t.status === 'running' && t.phase.includes('tool'))) {
      return '工具运行中'
    }
    if (isStreaming) return 'Agent 推理中'
    if (messages.length === 0) return '空闲'
    return '等待用户'
  }, [messages.length, statusTimeline, isStreaming])

  const reloadPlatformData = async () => {
    const [serverData, skillData] = await Promise.all([fetchMCPServers(), fetchSkills()])
    setServers(serverData.servers || [])
    setSkills(skillData.skills || [])
    if (!selectedServerId && serverData.servers?.[0]) {
      setSelectedServerId(serverData.servers[0].id)
    }
  }

  useEffect(() => {
    const token = localStorage.getItem('everloop_token')
    const storedUsername = localStorage.getItem('everloop_username')
    if (token) {
      setIsLoggedIn(true)
      setUsername(storedUsername || 'User')
    }

    const onAuthExpired = () => {
      setIsLoggedIn(false)
      setUsername('')
      clearMessages()
    }
    window.addEventListener('everloop-auth-expired', onAuthExpired)
    return () => window.removeEventListener('everloop-auth-expired', onAuthExpired)
  }, [clearMessages])

  useEffect(() => {
    if (!isLoggedIn) return
    fetchModels().then((data) => {
      if (data.models?.length) {
        setAvailableModels(data.models)
        if (data.default) setCurrentModel(data.default)
      }
    })
    reloadPlatformData().catch((err) => setPlatformNotice(err instanceof Error ? err.message : '平台数据加载失败'))
  }, [isLoggedIn])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('everloop_theme', theme)
  }, [theme])

  useEffect(() => {
    if (!selectedServerId) {
      setSelectedTools([])
      setToolSchemas([])
      return
    }
    fetchMCPTools(selectedServerId)
      .then((data) => {
        setSelectedTools(data.ui_metadata || [])
        setToolSchemas(data.llm_schema || [])
      })
      .catch((err) => setPlatformNotice(err instanceof Error ? err.message : 'MCP 工具加载失败'))
  }, [selectedServerId])

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

  return (
    <div className="app-root">
      <header className="topbar glass-card">
        <div className="brand">
          <div className="brand-mark">EL</div>
          <div>
            <div className="brand-title">EverLoop</div>
            <div className="brand-subtitle">Agent Platform</div>
          </div>
        </div>

        <div className="topbar-center">
          <div className={`status-badge ${isStreaming ? 'thinking' : ''}`}>
            <span className="dot" />
            {appStatusLabel}
          </div>
          {availableModels.length > 0 && (
            <select value={currentModel} onChange={(e) => setCurrentModel(e.target.value)}>
              {availableModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          )}
          <button className="btn" onClick={clearMessages}>
            新建任务
          </button>
        </div>

        <div className="topbar-right">
          <button className="btn" onClick={() => setTheme((v) => (v === 'light' ? 'dark' : 'light'))}>
            {theme === 'light' ? '深色' : '浅色'}
          </button>
          <span className="user-name">{username}</span>
          <button className="btn btn-danger" onClick={handleLogout}>
            退出
          </button>
        </div>
      </header>

      <div className="app-shell">
        <aside className="left-sidebar glass-card">
          <button
            className="new-task-btn"
            onClick={() => {
              clearMessages()
              setActiveView('workspace')
            }}
          >
            + 新建 Agent Run
          </button>

          <div className="sidebar-section">
            <div className="sidebar-title">平台导航</div>
            {views.map((view) => (
              <button
                key={view.id}
                className={`agent-item ${activeView === view.id ? 'active' : ''}`}
                onClick={() => setActiveView(view.id)}
              >
                <div className="agent-head">
                  <span className="agent-avatar">{view.label.slice(0, 1)}</span>
                  <div>
                    <div className="agent-name">{view.label}</div>
                    <div className="agent-desc">{view.desc}</div>
                  </div>
                </div>
                <span className={`status-dot ${activeView === view.id ? 'busy' : 'idle'}`} />
              </button>
            ))}
          </div>

          <div className="sidebar-section">
            <div className="sidebar-title">能力概览</div>
            <div className="capability-pill">MCP Servers <strong>{servers.length}</strong></div>
            <div className="capability-pill">Skills <strong>{skills.length}</strong></div>
            <div className="capability-pill">Tool Calls <strong>{toolCalls.length}</strong></div>
          </div>

          <div className="sidebar-footer">
            <div className="user-avatar">{username.slice(0, 1).toUpperCase()}</div>
            <div>
              <div className="footer-name">{username}</div>
              <div className="footer-workspace">当前线程 {threadId || '未创建'}</div>
            </div>
          </div>
        </aside>

        <main className="main-pane glass-card">
          {activeView === 'workspace' && (
            <div className="workspace-stack">
              {messages.length === 0 && (
                <div className="workspace-hero">
                  <img src={platformHero} alt="EverLoop Agent Platform" />
                  <div className="workspace-hero-copy">
                    <span>Agent Platform</span>
                    <h1>把 MCP、Skill 和 Trace 放进同一个工作台</h1>
                    <p>从任务运行、工具调试、参数校验到结果观测，EverLoop 会把每一次 Agent 行动摊开给你看。</p>
                  </div>
                </div>
              )}
              <ChatWindow
                title="Agent 工作台"
                description="运行任务、观察工具调用，并把 MCP 与 Skill 作为可调试能力使用。"
                onToggleRightPanel={() => setRightCollapsed((v) => !v)}
              />
            </div>
          )}
          {activeView === 'agents' && (
            <AgentHub
              currentModel={currentModel}
              servers={servers}
              skills={skills}
              toolSchemas={toolSchemas}
              onOpenWorkspace={() => setActiveView('workspace')}
            />
          )}
          {activeView === 'mcp' && (
            <MCPHub
              servers={servers}
              selectedServerId={selectedServer?.id || ''}
              tools={selectedTools}
              schemas={toolSchemas}
              notice={platformNotice}
              onSelectServer={setSelectedServerId}
              onReload={reloadPlatformData}
              onNotice={setPlatformNotice}
            />
          )}
          {activeView === 'skills' && (
            <SkillHub
              skills={skills}
              servers={servers}
              tools={selectedTools}
              selectedServerId={selectedServer?.id || ''}
              onSelectServer={setSelectedServerId}
              onReload={reloadPlatformData}
              onNotice={setPlatformNotice}
            />
          )}
          {activeView === 'trace' && <TraceHub />}
        </main>

        <aside className={`right-panel glass-card ${rightCollapsed ? 'collapsed' : ''}`}>
          <div className="right-header">
            <div className="right-tabs">
              <button className={rightTab === 'inspector' ? 'active' : ''} onClick={() => setRightTab('inspector')}>
                检查器
              </button>
              <button className={rightTab === 'activity' ? 'active' : ''} onClick={() => setRightTab('activity')}>
                活动
              </button>
              <button className={rightTab === 'context' ? 'active' : ''} onClick={() => setRightTab('context')}>
                上下文
              </button>
            </div>
            <button className="collapse-btn" onClick={() => setRightCollapsed((v) => !v)}>
              {rightCollapsed ? '<' : '>'}
            </button>
          </div>

          {!rightCollapsed && (
            <RightInspector
              tab={rightTab}
              activeView={activeView}
              servers={servers}
              skills={skills}
              tools={selectedTools}
              toolCalls={toolCalls}
              currentModel={currentModel}
              threadId={threadId}
              usage={usageSummary}
              timeline={statusTimeline}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

function AgentHub({
  currentModel,
  servers,
  skills,
  toolSchemas,
  onOpenWorkspace,
}: {
  currentModel: string
  servers: MCPServerItem[]
  skills: SkillItem[]
  toolSchemas: any[]
  onOpenWorkspace: () => void
}) {
  return (
    <section className="platform-page">
      <div className="page-head">
        <div>
          <h2>Agent 能力配置</h2>
          <p>查看当前 Agent 的模型、可见 MCP、Skill 和传给 LLM 的 tool schema。</p>
        </div>
        <button className="btn" onClick={onOpenWorkspace}>打开工作台</button>
      </div>

      <div className="metric-grid">
        <MetricCard label="当前模型" value={currentModel || '默认'} />
        <MetricCard label="MCP Servers" value={String(servers.length)} />
        <MetricCard label="Enabled Skills" value={String(skills.filter((s) => s.enabled).length)} />
        <MetricCard label="Visible Schemas" value={String(toolSchemas.length)} />
      </div>

      <div className="platform-section">
        <h3>LLM 可见工具 Schema</h3>
        <div className="schema-list">
          {toolSchemas.length === 0 ? (
            <div className="empty-tip">选择一个 MCP Server 后可预览其 tool schema。</div>
          ) : (
            toolSchemas.map((schema, idx) => {
              const fn = schema.function || schema
              return (
                <div key={`${fn.name}-${idx}`} className="schema-row">
                  <div>
                    <strong>{fn.name}</strong>
                    <span>{fn.description || '无描述'}</span>
                  </div>
                  <code>{Object.keys(fn.parameters?.properties || {}).join(', ') || 'no args'}</code>
                </div>
              )
            })
          )}
        </div>
      </div>
    </section>
  )
}

function MCPHub({
  servers,
  selectedServerId,
  tools,
  schemas,
  notice,
  onSelectServer,
  onReload,
  onNotice,
}: {
  servers: MCPServerItem[]
  selectedServerId: string
  tools: MCPToolMeta[]
  schemas: any[]
  notice: string
  onSelectServer: (id: string) => void
  onReload: () => Promise<void>
  onNotice: (value: string) => void
}) {
  const [name, setName] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [description, setDescription] = useState('')
  const [selectedTool, setSelectedTool] = useState('')
  const [toolArgs, setToolArgs] = useState('{}')
  const [toolResult, setToolResult] = useState('')
  const [busy, setBusy] = useState(false)

  const selectedSchema = useMemo(() => {
    const nameToFind = selectedTool || tools[0]?.tool_name
    return schemas.find((s) => (s.function || s).name === nameToFind)
  }, [schemas, selectedTool, tools])

  const handleCreateServer = async () => {
    if (!name.trim() || !endpoint.trim()) return
    setBusy(true)
    try {
      await createMCPServer({ name: name.trim(), endpoint_url: endpoint.trim(), description })
      setName('')
      setEndpoint('')
      setDescription('')
      onNotice('MCP Server 已创建')
      await onReload()
    } catch (err) {
      onNotice(err instanceof Error ? err.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const handleCallTool = async () => {
    const toolName = selectedTool || tools[0]?.tool_name
    if (!selectedServerId || !toolName) return
    setBusy(true)
    try {
      const parsed = JSON.parse(toolArgs || '{}')
      const result = await callMCPTool(selectedServerId, toolName, parsed)
      setToolResult(asJson(result))
      onNotice(result.ok ? '工具调用完成' : '工具调用返回错误')
    } catch (err) {
      setToolResult(err instanceof Error ? err.message : '调用失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="platform-page">
      <div className="page-head">
        <div>
          <h2>MCP Hub</h2>
          <p>管理 MCP Server、查看 tools/list、调试 tools/call，并创建 MCP Skill。</p>
        </div>
        <button className="btn" onClick={() => onReload()}>刷新</button>
      </div>
      <div className="visual-band">
        <img src={mcpNetwork} alt="MCP client server network" />
        <div>
          <span>MCP Runtime</span>
          <h3>Client 连接 Server，工具以协议化 schema 暴露</h3>
          <p>EverLoop 优先走 JSON-RPC MCP，自动回退 REST 兼容路径，并把 transport、lint 和 observation 都显示在 Trace 里。</p>
        </div>
      </div>
      {notice && <div className="notice-bar">{notice}</div>}

      <div className="split-layout">
        <div className="platform-section">
          <h3>Servers</h3>
          <div className="resource-list">
            {servers.map((server) => (
              <button
                key={server.id}
                className={`resource-row ${selectedServerId === server.id ? 'active' : ''}`}
                onClick={() => onSelectServer(server.id)}
              >
                <strong>{server.name}</strong>
                <span>{server.endpoint_url}</span>
                <em>{server.auth_type || 'none'}</em>
              </button>
            ))}
            {servers.length === 0 && <div className="empty-tip">暂无 MCP Server</div>}
          </div>

          <div className="form-grid">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Server name" />
            <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="http://127.0.0.1:9000/mcp" />
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="描述这个 MCP Server 的能力" />
            <button className="btn" disabled={busy || !name.trim() || !endpoint.trim()} onClick={handleCreateServer}>
              创建 MCP Server
            </button>
          </div>
        </div>

        <div className="platform-section">
          <h3>Tools</h3>
          <div className="tool-grid">
            {tools.map((tool) => (
              <button
                key={tool.tool_name}
                className={`tool-tile ${selectedTool === tool.tool_name ? 'active' : ''}`}
                onClick={() => setSelectedTool(tool.tool_name)}
              >
                <strong>{tool.display_name || tool.tool_name}</strong>
                <span>{tool.description || '无描述'}</span>
                <em>{tool.transport || 'transport'}</em>
              </button>
            ))}
            {tools.length === 0 && <div className="empty-tip">选择 Server 后加载工具。</div>}
          </div>

          <div className="debug-console">
            <div className="debug-head">
              <strong>Tool Debugger</strong>
              <span>{selectedTool || tools[0]?.tool_name || '未选择工具'}</span>
            </div>
            <pre>{asJson((selectedSchema?.function || selectedSchema)?.parameters || {})}</pre>
            <textarea value={toolArgs} onChange={(e) => setToolArgs(e.target.value)} />
            <button className="btn" disabled={busy || tools.length === 0} onClick={handleCallTool}>
              Try tools/call
            </button>
            {toolResult && <pre>{toolResult}</pre>}
          </div>
        </div>
      </div>
    </section>
  )
}

function SkillHub({
  skills,
  servers,
  tools,
  selectedServerId,
  onSelectServer,
  onReload,
  onNotice,
}: {
  skills: SkillItem[]
  servers: MCPServerItem[]
  tools: MCPToolMeta[]
  selectedServerId: string
  onSelectServer: (id: string) => void
  onReload: () => Promise<void>
  onNotice: (value: string) => void
}) {
  const [name, setName] = useState('')
  const [namespace, setNamespace] = useState('')
  const [description, setDescription] = useState('')
  const [toolFilter, setToolFilter] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const handleCreateSkill = async () => {
    if (!name.trim() || !selectedServerId) return
    setBusy(true)
    try {
      await createMCPSkill({
        name: name.trim(),
        namespace: namespace.trim() || undefined,
        description,
        mcp_server_id: selectedServerId,
        mcp_tool_filter: toolFilter,
      })
      setName('')
      setNamespace('')
      setDescription('')
      setToolFilter([])
      onNotice('MCP Skill 已创建')
      await onReload()
    } catch (err) {
      onNotice(err instanceof Error ? err.message : '创建 Skill 失败')
    } finally {
      setBusy(false)
    }
  }

  const handleToggle = async (skill: SkillItem) => {
    if (isBuiltinSkill(skill)) {
      onNotice('内置 Skill 已由系统托管，不能在这里禁用')
      return
    }
    await toggleSkill(skill.id, !skill.enabled)
    await onReload()
  }

  const handleSync = async (skill: SkillItem) => {
    if (isBuiltinSkill(skill)) {
      onNotice('内置 Skill 不需要同步 Schema')
      return
    }
    const result = await syncSkill(skill.id)
    onNotice(result.synced ? 'Schema 已同步' : result.last_error || '同步失败')
    await onReload()
  }

  return (
    <section className="platform-page">
      <div className="page-head">
        <div>
          <h2>Skill Hub</h2>
          <p>把 MCP Server 或部分 tools 包装成主 Agent 可调用的 Skill。</p>
        </div>
      </div>
      <div className="visual-band skill">
        <img src={skillWorkbench} alt="Skill workbench" />
        <div>
          <span>Skill Workbench</span>
          <h3>把工具能力变成 Agent 可理解的技能</h3>
          <p>MCP Skill 会以 tool name、description 和 task 参数暴露给主 Agent，模型选择后再进入 MCP 子 Agent 流程。</p>
        </div>
      </div>

      <div className="split-layout">
        <div className="platform-section">
          <h3>创建 MCP Skill</h3>
          <div className="form-grid">
            <select value={selectedServerId} onChange={(e) => onSelectServer(e.target.value)}>
              {servers.map((server) => (
                <option key={server.id} value={server.id}>{server.name}</option>
              ))}
            </select>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Skill name" />
            <input value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder="namespace，例如 market_research" />
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="给 LLM 看的 Skill description" />
          </div>
          <div className="tool-filter">
            {tools.map((tool) => (
              <label key={tool.tool_name}>
                <input
                  type="checkbox"
                  checked={toolFilter.includes(tool.tool_name)}
                  onChange={(e) => {
                    setToolFilter((prev) =>
                      e.target.checked
                        ? [...prev, tool.tool_name]
                        : prev.filter((item) => item !== tool.tool_name),
                    )
                  }}
                />
                {tool.tool_name}
              </label>
            ))}
          </div>
          <button className="btn" disabled={busy || !name.trim() || !selectedServerId} onClick={handleCreateSkill}>
            创建 Skill
          </button>
        </div>

        <div className="platform-section">
          <h3>Skills</h3>
          <div className="resource-list">
            {skills.map((skill) => {
              const builtin = isBuiltinSkill(skill)
              return (
                <div key={skill.id} className={`skill-row ${builtin ? 'builtin' : ''}`}>
                  <div>
                    <div className="skill-title-line">
                      <strong>{skill.name}</strong>
                      {builtin && <span className="pill success">内置</span>}
                      {skill.skill_type === 'mcp' && <span className="pill">MCP</span>}
                      {!skill.enabled && <span className="pill warn">已禁用</span>}
                    </div>
                    <span>{skill.namespace || skill.skill_type}</span>
                    <p>{skill.description || '无描述'}</p>
                    {builtin && (
                      <small>
                        已接入主 Agent 的 function calling：用户问天气、下雨、温度或出行天气时会自动选择
                        <code>skill_weather</code>。
                      </small>
                    )}
                  </div>
                  <div className="row-actions">
                    {builtin ? (
                      <>
                        {skill.homepage && (
                          <a className="btn subtle" href={skill.homepage} target="_blank" rel="noreferrer">
                            SKILL.md
                          </a>
                        )}
                        <button className="btn subtle" disabled>系统托管</button>
                      </>
                    ) : (
                      <>
                        <button className="btn" onClick={() => handleToggle(skill)}>{skill.enabled ? '禁用' : '启用'}</button>
                        {skill.skill_type === 'mcp' && <button className="btn" onClick={() => handleSync(skill)}>同步</button>}
                      </>
                    )}
                  </div>
                </div>
              )
            })}
            {skills.length === 0 && <div className="empty-tip">暂无 Skill</div>}
          </div>
        </div>
      </div>
    </section>
  )
}

function isBuiltinSkill(skill: SkillItem): boolean {
  return skill.read_only === true || skill.version === 'builtin' || skill.owner_id === 'system'
}

function TraceHub() {
  const timeline = useChatStore((s) => s.statusTimeline)
  const usage = useChatStore((s) => s.usageSummary)
  const messages = useChatStore((s) => s.messages)

  return (
    <section className="platform-page">
      <div className="page-head">
        <div>
          <h2>Run Trace</h2>
          <p>查看 Agent loop、function-call linter、MCP transport 和 observation。</p>
        </div>
      </div>

      <div className="metric-grid">
        <MetricCard label="Input Tokens" value={String(usage.inputTokens)} />
        <MetricCard label="Output Tokens" value={String(usage.outputTokens)} />
        <MetricCard label="Cache Read" value={String(usage.cacheReadTokens)} />
        <MetricCard label="Cost" value={`$${usage.estimatedCostUsd.toFixed(4)}`} />
      </div>

      <div className="trace-layout">
        <div className="platform-section">
          <h3>Timeline</h3>
          <div className="trace-list">
            {timeline.map((event) => (
              <div key={event.id} className={`trace-row ${event.status}`}>
                <span>{event.seq}</span>
                <strong>{event.phase}</strong>
                <p>{event.message}</p>
                <em>{event.status}</em>
              </div>
            ))}
            {timeline.length === 0 && <div className="empty-tip">运行 Agent 后会出现 trace。</div>}
          </div>
        </div>
        <div className="platform-section">
          <h3>Messages</h3>
          <div className="message-inspector">
            {messages.map((message) => (
              <div key={message.id} className="message-inspector-row">
                <strong>{message.role}</strong>
                <p>{message.content || message.thinkContent || `${message.toolCalls.length} tool calls`}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function RightInspector({
  tab,
  activeView,
  servers,
  skills,
  tools,
  toolCalls,
  currentModel,
  threadId,
  usage,
  timeline,
}: {
  tab: RightTab
  activeView: ViewKey
  servers: MCPServerItem[]
  skills: SkillItem[]
  tools: MCPToolMeta[]
  toolCalls: Array<{ id: string; toolName: string; status: string; resultPreview?: string }>
  currentModel: string
  threadId: string | null
  usage: { inputTokens: number; outputTokens: number; estimatedCostUsd: number }
  timeline: Array<{ id: string; phase: string; status: string; message: string }>
}) {
  if (tab === 'activity') {
    return (
      <div className="right-content">
        <div className="panel-list">
          {toolCalls.slice(-10).reverse().map((call) => (
            <div key={call.id} className="activity-item">
              <span className={`log-dot ${call.status === 'running' ? 'running' : call.status === 'error' ? 'error' : 'done'}`} />
              <div>
                <div>{call.toolName}</div>
                <em>{call.resultPreview || call.status}</em>
              </div>
            </div>
          ))}
          {toolCalls.length === 0 && <div className="empty-tip">暂无工具调用</div>}
        </div>
      </div>
    )
  }

  if (tab === 'context') {
    return (
      <div className="right-content">
        <div className="panel-list">
          <InfoRow label="当前视图" value={activeView} />
          <InfoRow label="线程 ID" value={threadId || '未创建'} />
          <InfoRow label="模型" value={currentModel || '默认'} />
          <InfoRow label="MCP Server" value={String(servers.length)} />
          <InfoRow label="Skill" value={String(skills.length)} />
          <InfoRow label="Cost" value={`$${usage.estimatedCostUsd.toFixed(4)}`} />
        </div>
      </div>
    )
  }

  return (
    <div className="right-content">
      <div className="panel-list">
        <div className="artifact-card">
          <div className="artifact-title">Platform Inspector</div>
          <div className="artifact-meta">MCP / Skill / Trace</div>
          <div className="artifact-preview">
            当前 Server 暴露 {tools.length} 个工具，最近 trace 事件 {timeline.length} 条。
          </div>
        </div>
        {timeline.slice(-8).reverse().map((event) => (
          <div key={event.id} className={`ai-event ${event.status}`}>
            <span className="event-phase">{event.phase}</span>
            <span className="event-message">{event.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
