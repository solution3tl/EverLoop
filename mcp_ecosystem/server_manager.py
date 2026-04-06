"""
MCP Server 管理 - 物业管理中心
负责 MCP Server 的全生命周期管理、权限隔离、工具 Schema 解析
"""
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import crud
from database.models import MCPServer


class PermissionDeniedError(Exception):
    pass


class MCPServerNotFoundError(Exception):
    pass


async def create_mcp_server(
    name: str,
    endpoint_url: str,
    owner_id: str,
    auth_type: str = "none",
    auth_credential: str = None,
    is_public: bool = False,
    description: str = "",
) -> MCPServer:
    """
    创建 MCP Server 记录。
    尝试连接验证 endpoint_url 可达性（失败也允许创建，只记录警告）。
    """
    # 写入数据库
    server = await crud.create_mcp_server(
        name=name,
        endpoint_url=endpoint_url,
        owner_id=owner_id,
        auth_type=auth_type,
        auth_credential=auth_credential,
        is_public=is_public,
        description=description,
    )

    # 连接测试（非阻塞，失败不影响创建）
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(endpoint_url + "/health", follow_redirects=True)
            if resp.status_code >= 500:
                print(f"[WARN] MCP Server {name} 健康检查失败：{resp.status_code}")
    except Exception as e:
        print(f"[WARN] MCP Server {name} 连接测试失败（可忽略）：{e}")

    return server


async def get_mcp_server(
    server_id: str,
    requester_id: str,
    is_admin: bool = False,
) -> MCPServer:
    """获取 MCP Server（含权限校验）"""
    server = await crud.get_mcp_server_by_id(server_id)
    if not server:
        raise MCPServerNotFoundError(f"MCP Server {server_id} 不存在")

    if not is_admin and server.owner_id != requester_id and not server.is_public:
        raise PermissionDeniedError(f"无权访问 MCP Server {server_id}")

    return server


async def list_mcp_servers(requester_id: str, is_admin: bool = False) -> List[MCPServer]:
    """列出可见 MCP Server"""
    return await crud.list_mcp_servers(requester_id=requester_id, is_admin=is_admin)


async def parse_server_tools_schema(
    server_id: str,
    requester_id: str,
    is_admin: bool = False,
) -> Tuple[List[Dict], List[Dict]]:
    """
    解析 MCP Server 暴露的工具列表。
    返回：(llm_schema_list, ui_metadata_list)
    """
    server = await get_mcp_server(server_id, requester_id, is_admin)

    # 尝试从 MCP Server 获取工具列表
    tools_schema = []
    ui_metadata = []

    try:
        headers = {}
        if server.auth_type == "apikey" and server.auth_credential:
            headers["Authorization"] = f"Bearer {server.auth_credential}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{server.endpoint_url}/tools/list",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_tools = data.get("tools", [])
                for tool in raw_tools:
                    tool_name = tool.get("name", "")
                    description = tool.get("description", "")
                    parameters = tool.get("inputSchema", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    })

                    tools_schema.append({
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": description,
                            "parameters": parameters,
                        }
                    })
                    ui_metadata.append({
                        "tool_name": tool_name,
                        "display_name": tool.get("display_name", tool_name),
                        "description": description,
                        "server_id": server_id,
                        "server_name": server.name,
                    })
    except Exception as e:
        print(f"[WARN] 获取 MCP Server {server.name} 工具列表失败：{e}")

    return tools_schema, ui_metadata


async def cleanup_stale_servers(stale_days: int = 30, timezone: str = "Asia/Shanghai") -> int:
    """禁用超过 N 天未使用的 MCP Server（由 janitor_daemon 调用）"""
    # 简化实现：实际生产中应更新 is_active 字段
    # 此处只记录日志
    print(f"[Janitor] 扫描超过 {stale_days} 天未使用的 MCP Server...")
    return 0
