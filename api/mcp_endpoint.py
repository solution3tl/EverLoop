"""
MCP Server REST 管理接口
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict, Optional

from mcp_ecosystem import server_manager
from mcp_ecosystem import client as mcp_client
from function_calling.fc_validator import validate_tool_call_against_schema

router = APIRouter()


class CreateMCPServerRequest(BaseModel):
    name: str
    endpoint_url: str
    auth_type: str = "none"
    auth_credential: Optional[str] = None
    is_public: bool = False
    description: str = ""


class CallMCPToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}


@router.post("/servers")
async def create_server(req: CreateMCPServerRequest, request: Request):
    """创建 MCP Server"""
    user_id = getattr(request.state, "user_id", "anonymous")
    server = await server_manager.create_mcp_server(
        name=req.name,
        endpoint_url=req.endpoint_url,
        owner_id=user_id,
        auth_type=req.auth_type,
        auth_credential=req.auth_credential,
        is_public=req.is_public,
        description=req.description,
    )
    return {
        "id": str(server.id),
        "name": server.name,
        "endpoint_url": server.endpoint_url,
        "is_public": server.is_public,
        "created_at": server.created_at.isoformat() if server.created_at else None,
    }


@router.get("/servers")
async def list_servers(request: Request):
    """列出可见 MCP Server"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)
    servers = await server_manager.list_mcp_servers(user_id, is_admin)
    return {
        "servers": [
            {
                "id": str(s.id),
                "name": s.name,
                "endpoint_url": s.endpoint_url,
                "description": s.description,
                "is_public": s.is_public,
                "auth_type": s.auth_type,
            }
            for s in servers
        ]
    }


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str, request: Request):
    """删除 MCP Server"""
    user_id = getattr(request.state, "user_id", "anonymous")
    from database import crud
    success = await crud.delete_mcp_server(server_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Server 不存在或无权删除")
    return {"success": True}


@router.get("/servers/{server_id}/tools")
async def get_server_tools(server_id: str, request: Request):
    """获取 MCP Server 的工具 Schema"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)
    try:
        llm_schema, ui_metadata = await server_manager.parse_server_tools_schema(
            server_id=server_id,
            requester_id=user_id,
            is_admin=is_admin,
        )
        return {"llm_schema": llm_schema, "ui_metadata": ui_metadata}
    except server_manager.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    except server_manager.PermissionDeniedError:
        raise HTTPException(status_code=403, detail="无权访问此 MCP Server")


@router.post("/servers/{server_id}/tools/call")
async def call_server_tool(server_id: str, req: CallMCPToolRequest, request: Request):
    """调试调用 MCP Server 的单个工具。"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)
    try:
        server = await server_manager.get_mcp_server(server_id, requester_id=user_id, is_admin=is_admin)
        llm_schema, _ = await server_manager.parse_server_tools_schema(
            server_id=server_id,
            requester_id=user_id,
            is_admin=is_admin,
        )
    except server_manager.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    except server_manager.PermissionDeniedError:
        raise HTTPException(status_code=403, detail="无权访问此 MCP Server")

    mcp_tool_map = {
        s.get("function", s).get("name"): True
        for s in llm_schema
        if isinstance(s, dict) and s.get("function", s).get("name")
    }
    ok, reason, normalized_args = validate_tool_call_against_schema(
        tool_name=req.name,
        tool_args=req.arguments,
        tools_schema=llm_schema,
        tools_map=mcp_tool_map,
    )
    if not ok:
        return {
            "ok": False,
            "is_error": True,
            "transport": "lint",
            "content": f"参数校验失败：{reason}",
        }

    try:
        result, transport = await mcp_client.call_tool(server, req.name, normalized_args)
        return {
            "ok": not bool(result.get("is_error")),
            "is_error": bool(result.get("is_error")),
            "transport": transport,
            "content": result.get("content", result),
        }
    except Exception as e:
        return {
            "ok": False,
            "is_error": True,
            "transport": "error",
            "content": f"MCP 调用失败：{str(e)}",
        }


@router.post("/knowledge/upload")
async def upload_knowledge(request: Request):
    """上传知识库文档"""
    user_id = getattr(request.state, "user_id", "anonymous")
    from fastapi import UploadFile, File, Form
    # 简化实现：返回说明
    return {"message": "知识库上传功能需通过表单方式调用，请使用 multipart/form-data"}
