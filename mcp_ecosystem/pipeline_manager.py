"""
MCP 执行流水线 - 五步流水线工厂
建连 -> 提问 LLM -> 执行工具 -> 缝合结果 -> 再次调用 LLM
"""
import asyncio
import json
from typing import Callable, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage

from database.models import MCPServer
from function_calling.fc_validator import validate_tool_call_against_schema
from mcp_ecosystem import client as mcp_client


async def arun_pipeline(
    mcp_server: MCPServer,
    user_query: str,
    tools_schema: List[Dict],
    llm: BaseChatModel,
    stream_writer: Optional[Callable] = None,
    child_thread_id: str = "",
) -> str:
    """
    MCP 五步执行流水线。
    返回最终整合回答文本。
    """

    async def _write(packet: dict):
        if stream_writer:
            try:
                if asyncio.iscoroutinefunction(stream_writer):
                    await stream_writer(packet)
                else:
                    stream_writer(packet)
            except Exception:
                pass

    def _normalize_tool_schema(schema: Dict) -> Dict:
        if isinstance(schema, dict) and schema.get("type") == "function" and "function" in schema:
            return schema["function"]
        return schema

    def _content_to_text(data) -> str:
        if isinstance(data, str):
            return data
        return json.dumps(data, ensure_ascii=False)

    # Step 1: 建立网络连接（建立 httpx 客户端）
    await _write({
        "type": "loop_status",
        "phase": "mcp_connect",
        "status": "running",
        "message": f"连接 MCP Server: {mcp_server.name}",
    })
    await _write({
        "type": "loop_status",
        "phase": "mcp_connect",
        "status": "done",
        "message": f"MCP Server 已就绪: {mcp_server.name}",
    })

    # Step 2: 首次 LLM 调用
    if tools_schema:
        llm_with_tools = llm.bind_tools([_normalize_tool_schema(s) for s in tools_schema])
    else:
        llm_with_tools = llm

    messages = [HumanMessage(content=user_query)]
    await _write({
        "type": "loop_status",
        "phase": "mcp_llm",
        "status": "running",
        "message": "MCP 子 Agent 正在选择工具",
    })
    first_response = await llm_with_tools.ainvoke(messages)
    tool_calls = getattr(first_response, "tool_calls", []) or []
    await _write({
        "type": "loop_status",
        "phase": "mcp_llm",
        "status": "done",
        "message": f"MCP 子 Agent 选择了 {len(tool_calls)} 个工具",
    })

    # 无 tool_calls 直接跳到 Step 5
    if not tool_calls:
        content = first_response.content if isinstance(first_response.content, str) else str(first_response.content)
        return content

    # Step 3: 执行工具调用
    messages.append(first_response)
    tool_results = []

    for tc in tool_calls:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        tool_call_id = tc.get("id") or f"mcp_call_{len(tool_results)}"

        event_tool_call_id = tool_call_id or f"{child_thread_id}:{tool_name}"

        await _write({
            "type": "tool_call_start",
            "tool_name": f"{mcp_server.name}.{tool_name}",
            "tool_args": tool_args,
            "tool_call_id": event_tool_call_id,
        })
        await _write({
            "type": "loop_status",
            "phase": "mcp_tool",
            "status": "running",
            "message": f"通过 MCP 调用 {tool_name}",
        })

        mcp_tool_map = {
            s.get("function", s).get("name"): True
            for s in tools_schema
            if isinstance(s, dict) and s.get("function", s).get("name")
        }
        valid_call, validation_reason, normalized_args = validate_tool_call_against_schema(
            tool_name=tool_name,
            tool_args=tool_args,
            tools_schema=tools_schema,
            tools_map=mcp_tool_map,
        )

        if not valid_call:
            result_text = f"[错误] MCP 工具调用参数校验失败：{validation_reason}。请根据工具 schema 重新生成该 function call。"
            is_error = True
            await _write({
                "type": "loop_status",
                "phase": "mcp_tool_lint",
                "status": "error",
                "message": f"{tool_name} 参数校验失败：{validation_reason}",
            })
        else:
            await _write({
                "type": "loop_status",
                "phase": "mcp_tool_lint",
                "status": "done",
                "message": f"{tool_name} 参数校验通过",
            })
            try:
                result_data, transport = await mcp_client.call_tool(mcp_server, tool_name, normalized_args)
                result_text = _content_to_text(result_data.get("content", result_data))
                is_error = bool(result_data.get("is_error"))
                await _write({
                    "type": "loop_status",
                    "phase": "mcp_transport",
                    "status": "done",
                    "message": f"{tool_name} 使用 {transport} transport 调用完成",
                })
            except Exception as e:
                result_text = f"MCP 连接异常：{str(e)}"
                is_error = True

        await _write({
            "type": "tool_call_done",
            "tool_name": f"{mcp_server.name}.{tool_name}",
            "result_preview": result_text[:200],
            "tool_call_id": event_tool_call_id,
        })
        await _write({
            "type": "observation",
            "tool_use_id": event_tool_call_id,
            "tool_name": f"{mcp_server.name}.{tool_name}",
            "is_error": is_error,
            "content_preview": result_text[:200],
        })
        await _write({
            "type": "loop_status",
            "phase": "mcp_tool",
            "status": "error" if is_error else "done",
            "message": f"{tool_name} 调用{'失败' if is_error else '完成'}",
        })

        tool_results.append(ToolMessage(content=result_text, tool_call_id=tool_call_id))

    # Step 4: 缝合上下文
    messages.extend(tool_results)

    # Step 5: 二次 LLM 调用（不带 tools_schema，获取整合回答）
    await _write({
        "type": "loop_status",
        "phase": "mcp_synthesis",
        "status": "running",
        "message": "MCP 子 Agent 正在整合工具结果",
    })
    final_response = await llm.ainvoke(messages)
    await _write({
        "type": "loop_status",
        "phase": "mcp_synthesis",
        "status": "done",
        "message": "MCP 子 Agent 整合完成",
    })
    return final_response.content if isinstance(final_response.content, str) else str(final_response.content)
