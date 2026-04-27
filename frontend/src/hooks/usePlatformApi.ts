const envApiBase = ((import.meta as any).env?.VITE_API_BASE || '').replace(/\/$/, '')
const API_BASES = [
  ...(envApiBase ? [envApiBase] : []),
  '/api',
  'http://127.0.0.1:8001/api',
  'http://localhost:8001/api',
]

export interface MCPServerItem {
  id: string
  name: string
  endpoint_url: string
  description: string
  is_public: boolean
  auth_type: string
}

export interface MCPToolMeta {
  tool_name: string
  display_name: string
  description: string
  server_id: string
  server_name: string
  transport?: string
}

export interface SkillItem {
  id: string
  name: string
  description: string
  version: string
  is_public: boolean
  owner_id: string
  skill_type: string
  enabled: boolean
  mcp_server_id?: string | null
  namespace?: string | null
  source?: string | null
  homepage?: string | null
  read_only?: boolean
  last_error?: string | null
}

function getToken(): string {
  return localStorage.getItem('everloop_token') || ''
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let lastError: unknown = null
  for (const base of API_BASES) {
    try {
      const response = await fetch(`${base}${path}`, {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
          ...(init.headers || {}),
        },
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`)
      }
      return data as T
    } catch (err) {
      lastError = err
    }
  }
  throw lastError instanceof Error ? lastError : new Error('请求失败')
}

export async function fetchMCPServers() {
  return apiRequest<{ servers: MCPServerItem[] }>('/mcp/servers')
}

export async function createMCPServer(payload: {
  name: string
  endpoint_url: string
  description?: string
  auth_type?: string
  auth_credential?: string
  is_public?: boolean
}) {
  return apiRequest<MCPServerItem>('/mcp/servers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function fetchMCPTools(serverId: string) {
  return apiRequest<{ llm_schema: any[]; ui_metadata: MCPToolMeta[] }>(`/mcp/servers/${serverId}/tools`)
}

export async function callMCPTool(serverId: string, name: string, argumentsValue: Record<string, unknown>) {
  return apiRequest<{ ok: boolean; is_error: boolean; transport: string; content: unknown }>(
    `/mcp/servers/${serverId}/tools/call`,
    {
      method: 'POST',
      body: JSON.stringify({ name, arguments: argumentsValue }),
    },
  )
}

export async function fetchSkills() {
  return apiRequest<{ skills: SkillItem[] }>('/skill/list')
}

export async function createMCPSkill(payload: {
  name: string
  description?: string
  mcp_server_id: string
  namespace?: string
  mcp_tool_filter?: string[]
  is_public?: boolean
}) {
  return apiRequest<SkillItem>('/skill/create-mcp', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function toggleSkill(skillId: string, enabled: boolean) {
  return apiRequest<{ skill_id: string; enabled: boolean }>(`/skill/${skillId}/toggle`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  })
}

export async function syncSkill(skillId: string) {
  return apiRequest<{ skill_id: string; synced: boolean; last_error?: string | null }>(`/skill/${skillId}/sync`, {
    method: 'POST',
  })
}
