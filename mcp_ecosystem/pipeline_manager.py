"""
MCP 执行流水线 - 五步流水线工厂
建连 -> 提问 LLM -> 执行工具 -> 缝合结果 -> 再次调用 LLM
"""
import json
from typing import Callable, Dict, List, Optional

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from database.models import MCPServer


async def arun_pipeline(
    mcp_server: MCPServer,
    user_query: str,
    tools_schema: List[Dict],
    llm: BaseChatModel,
    stream_writer: Optional[Callable] = None,
) -> str:
    """
    MCP 五步执行流水线。
    返回最终整合回答文本。
    """

    async def _write(packet: dict):
        if stream_writer:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(stream_writer):
                    await stream_writer(packet)
                else:
                    stream_writer(packet)
            except Exception:
                pass

    # Step 1: 建立网络连接（建立 httpx 客户端）
    headers = {}
    if mcp_server.auth_type == "apikey" and mcp_server.auth_credential:
        headers["Authorization"] = f"Bearer {mcp_server.auth_credential}"

    # Step 2: 首次 LLM 调用
    if tools_schema:
        llm_with_tools = llm.bind_tools(tools_schema)
    else:
        llm_with_tools = llm

    messages = [HumanMessage(content=user_query)]
    first_response = await llm_with_tools.ainvoke(messages)
    tool_calls = getattr(first_response, "tool_calls", []) or []

    # 无 tool_calls 直接跳到 Step 5
    if not tool_calls:
        content = first_response.content if isinstance(first_response.content, str) else str(first_response.content)
        return content

    # Step 3: 执行工具调用
    messages.append(first_response)
    tool_results = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            tool_call_id = tc.get("id", "")

            await _write({
                "type": "custom_status",
                "status": "running",
                "message": f"正在通过 MCP 调用 {tool_name}...",
            })

            try:
                resp = await client.post(
                    f"{mcp_server.endpoint_url}/tools/call",
                    headers=headers,
                    json={"name": tool_name, "arguments": tool_args},
                )
                if resp.status_code == 200:
                    result_data = resp.json()
                    result_text = json.dumps(result_data.get("content", result_data), ensure_ascii=False)
                else:
                    result_text = f"工具调用失败（HTTP {resp.status_code}）"
            except Exception as e:
                result_text = f"MCP 连接异常：{str(e)}"

            await _write({
                "type": "custom_status",
                "status": "completed",
                "message": f"{tool_name} 调用完成",
            })

            tool_results.append(ToolMessage(content=result_text, tool_call_id=tool_call_id))

    # Step 4: 缝合上下文
    messages.extend(tool_results)

    # Step 5: 二次 LLM 调用（不带 tools_schema，获取整合回答）
    final_response = await llm.ainvoke(messages)
    return final_response.content if isinstance(final_response.content, str) else str(final_response.content)
