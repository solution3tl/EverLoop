"""
MCP HTTP client adapter.

优先使用 MCP 的 JSON-RPC 2.0 方法：
  - tools/list
  - tools/call

同时保留项目早期的 REST 兼容路径：
  - GET  /tools/list
  - POST /tools/call
"""
import itertools
from typing import Any, Dict, List, Tuple

import httpx

from database.models import MCPServer


_REQUEST_IDS = itertools.count(1)


class MCPClientError(Exception):
    pass


def build_auth_headers(server: MCPServer) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if server.auth_type == "apikey" and server.auth_credential:
        headers["Authorization"] = f"Bearer {server.auth_credential}"
    return headers


async def list_tools(server: MCPServer) -> Tuple[List[Dict[str, Any]], str]:
    headers = build_auth_headers(server)

    try:
        headers = await _with_initialized_session(server.endpoint_url, headers)
        data = await _json_rpc(
            server.endpoint_url,
            method="tools/list",
            params={},
            headers=headers,
        )
        tools = data.get("tools", []) if isinstance(data, dict) else []
        if isinstance(tools, list):
            return tools, "jsonrpc"
    except Exception:
        pass

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{server.endpoint_url.rstrip('/')}/tools/list",
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        tools = data.get("tools", []) if isinstance(data, dict) else []
        if not isinstance(tools, list):
            raise MCPClientError("tools/list 返回格式无效：缺少 tools 数组")
        return tools, "rest"


async def call_tool(server: MCPServer, tool_name: str, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    headers = build_auth_headers(server)

    try:
        headers = await _with_initialized_session(server.endpoint_url, headers)
        data = await _json_rpc(
            server.endpoint_url,
            method="tools/call",
            params={"name": tool_name, "arguments": arguments or {}},
            headers=headers,
            timeout=30.0,
        )
        return _normalize_call_result(data), "jsonrpc"
    except Exception:
        pass

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{server.endpoint_url.rstrip('/')}/tools/call",
            headers=headers,
            json={"name": tool_name, "arguments": arguments or {}},
        )
        if resp.status_code != 200:
            return {
                "content": f"工具调用失败（HTTP {resp.status_code}）",
                "is_error": True,
            }, "rest"
        return _normalize_call_result(resp.json()), "rest"


async def _json_rpc(
    endpoint_url: str,
    *,
    method: str,
    params: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float = 10.0,
) -> Any:
    result, _ = await _json_rpc_with_response_headers(
        endpoint_url,
        method=method,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    return result


async def _json_rpc_with_response_headers(
    endpoint_url: str,
    *,
    method: str,
    params: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float = 10.0,
) -> Tuple[Any, httpx.Headers]:
    payload = {
        "jsonrpc": "2.0",
        "id": next(_REQUEST_IDS),
        "method": method,
        "params": params,
    }
    rpc_headers = {
        **headers,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(endpoint_url, headers=rpc_headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, dict):
        raise MCPClientError("JSON-RPC 响应不是 object")
    if data.get("error"):
        raise MCPClientError(str(data["error"]))
    return data.get("result", {}), resp.headers


async def _with_initialized_session(endpoint_url: str, headers: Dict[str, str]) -> Dict[str, str]:
    """
    MCP 标准包含 initialize 生命周期；部分简化服务允许直接 tools/list。
    这里尽量握手，失败则保留原 headers 继续尝试工具方法。
    """
    try:
        _, response_headers = await _json_rpc_with_response_headers(
            endpoint_url,
            method="initialize",
            params={
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "EverLoop", "version": "2.0.0"},
            },
            headers=headers,
            timeout=10.0,
        )
        session_id = response_headers.get("mcp-session-id") or response_headers.get("Mcp-Session-Id")
        next_headers = dict(headers)
        if session_id:
            next_headers["Mcp-Session-Id"] = session_id
        await _send_initialized_notification(endpoint_url, next_headers)
        return next_headers
    except Exception:
        return headers


async def _send_initialized_notification(endpoint_url: str, headers: Dict[str, str]) -> None:
    payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    rpc_headers = {
        **headers,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(endpoint_url, headers=rpc_headers, json=payload)
    except Exception:
        pass


def _normalize_call_result(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"content": data, "is_error": False}
    return {
        "content": data.get("content", data),
        "is_error": bool(data.get("isError") or data.get("is_error")),
    }
