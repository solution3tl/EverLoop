"""
流程控制中间件 - 包含 awrap_model_call, aafter_model, awrap_tool_call
stream_writer 通过 ContextVar 在每次请求时动态注入，middleware 内部通过 _stream_writer_var.get() 取值
"""
import json
import asyncio
from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

# ContextVar: 每次请求时由 chat_endpoint.py 设置，middleware 内部读取
_stream_writer_var: ContextVar[Optional[Callable]] = ContextVar("stream_writer", default=None)
_thread_id_var: ContextVar[Optional[str]] = ContextVar("thread_id", default=None)


def get_stream_writer() -> Optional[Callable]:
    return _stream_writer_var.get()


def get_thread_id() -> Optional[str]:
    return _thread_id_var.get()


async def _safe_write(writer: Optional[Callable], packet: dict):
    """安全写入流（忽略 None writer）"""
    if writer is None:
        return
    try:
        if asyncio.iscoroutinefunction(writer):
            await writer(packet)
        else:
            writer(packet)
    except Exception:
        pass


async def awrap_model_call(state: dict, tools_schema: List[Dict], llm, **kwargs) -> dict:
    """
    大模型调用包装器：
    - 将 tools_schema 绑定到 llm
    - 使用 astream 逐 token 流式调用
    - 文本 token → 通过 stream_writer 推送前端（打字机效果）
    - tool_call chunk → 积累参数片段，构造完整 AIMessage
    返回更新后的 state
    """
    writer = get_stream_writer()
    messages = state.get("messages", [])

    llm_with_tools = llm.bind_tools(tools_schema) if tools_schema else llm

    # 收集流式输出
    full_content = ""
    tool_calls_buffer: Dict[int, Dict] = {}  # index -> tool_call dict
    final_chunk = None

    try:
        async for chunk in llm_with_tools.astream(messages):
            # 文本内容直接推送
            if hasattr(chunk, "content") and chunk.content:
                text_part = chunk.content if isinstance(chunk.content, str) else ""
                if text_part:
                    full_content += text_part
                    await _safe_write(writer, {
                        "type": "text",
                        "content": text_part,
                        "is_end": False,
                    })

            # 积累 tool_calls
            if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                for tc_chunk in chunk.tool_call_chunks:
                    idx = tc_chunk.get("index", 0)
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc_chunk.get("id", ""),
                            "name": tc_chunk.get("name", ""),
                            "args": "",
                            "type": "tool_call",
                        }
                    else:
                        if tc_chunk.get("id"):
                            tool_calls_buffer[idx]["id"] = tc_chunk["id"]
                        if tc_chunk.get("name"):
                            tool_calls_buffer[idx]["name"] = tc_chunk["name"]
                    tool_calls_buffer[idx]["args"] += tc_chunk.get("args", "")

            final_chunk = chunk
    except Exception as e:
        # LLM 调用异常：写入兜底内容
        error_text = f"模型调用异常：{str(e)}"
        await _safe_write(writer, {"type": "text", "content": error_text, "is_end": True})
        new_messages = list(messages) + [AIMessage(content=error_text)]
        return {**state, "messages": new_messages}

    # 解析 tool_calls
    tool_calls = []
    for idx in sorted(tool_calls_buffer.keys()):
        tc = tool_calls_buffer[idx]
        try:
            args = json.loads(tc["args"]) if tc["args"] else {}
        except json.JSONDecodeError:
            args = {"raw": tc["args"]}
        tool_calls.append({
            "id": tc["id"] or f"call_{idx}",
            "name": tc["name"],
            "args": args,
            "type": "tool_call",
        })

    # 构造 AIMessage
    ai_message = AIMessage(content=full_content, tool_calls=tool_calls)
    new_messages = list(messages) + [ai_message]

    # 更新调用计数
    call_cnt = state.get("model_call_cnt", 0) + 1
    return {**state, "messages": new_messages, "model_call_cnt": call_cnt}


async def aafter_model(state: dict, max_tool_calls: int = 5) -> str:
    """
    模型调用后路由决策器：
    - 检查最后一条消息是否含 tool_calls
    - 超过 max_tool_calls 时注入强制审视指令并返回 "retry"
    - 有 tool_calls 且未超限 → "continue"
    - 无 tool_calls → "end"
    """
    messages = state.get("messages", [])
    if not messages:
        return "end"

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", []) or []

    if not tool_calls:
        return "end"

    call_cnt = state.get("model_call_cnt", 0)
    if call_cnt > max_tool_calls:
        return "retry"  # 调用方需注入 SystemMessage 并重新规划

    return "continue"


async def awrap_tool_call(
    state: dict,
    tools_map: Dict[str, Callable],
    user_permissions: Set[str] = None,
    tool_registry=None,
    **kwargs,
) -> dict:
    """
    工具调用执行器：
    Step 1: 广播开始状态
    Step 1.5: 操作记录（写入 state 的 operation_log）
    Step 2: 安全校验（fc_validator）
    Step 3: 执行工具
    Step 4: 广播结束状态
    Step 5: 构造 ToolMessage 追加到 messages
    """
    writer = get_stream_writer()
    messages = state.get("messages", [])
    operation_log = list(state.get("operation_log", []))

    if not messages:
        return state

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", []) or []

    if not tool_calls:
        return state

    new_tool_messages = []

    for tc in tool_calls:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        tool_call_id = tc.get("id", "")

        # Step 1: 广播开始
        await _safe_write(writer, {
            "type": "custom_status",
            "status": "running",
            "message": f"正在调用 {tool_name}...",
        })

        # Step 1.5: 操作记录
        operation_log.append({
            "tool_name": tool_name,
            "arguments": tool_args,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Step 2: 安全校验
        if user_permissions is not None:
            # 修复问题 #9: 原代码中条件逻辑反转，allowed 永远等于 user_permissions
            allowed = user_permissions  # 直接使用传入的权限集合
            if tool_name not in allowed and "*" not in allowed:
                await _safe_write(writer, {
                    "type": "custom_status",
                    "status": "completed",
                    "message": f"{tool_name} 调用被拒绝（无权限）",
                })
                new_tool_messages.append(
                    ToolMessage(
                        content=f"权限错误：当前用户无权调用工具 {tool_name}",
                        tool_call_id=tool_call_id,
                    )
                )
                continue

        # Step 3: 执行工具
        tool_func = tools_map.get(tool_name)
        if tool_func is None:
            result_content = f"错误：工具 {tool_name} 不存在"
        else:
            try:
                if asyncio.iscoroutinefunction(tool_func):
                    result = await tool_func(**tool_args)
                else:
                    result = tool_func(**tool_args)
                result_content = str(result) if result is not None else "（无返回值）"
            except Exception as e:
                result_content = f"工具 {tool_name} 执行异常：{str(e)}"

        # Step 4: 广播结束
        await _safe_write(writer, {
            "type": "custom_status",
            "status": "completed",
            "message": f"{tool_name} 调用完成",
        })

        # Step 5: 构造 ToolMessage
        new_tool_messages.append(
            ToolMessage(content=result_content, tool_call_id=tool_call_id)
        )

    new_messages = list(messages) + new_tool_messages
    return {**state, "messages": new_messages, "operation_log": operation_log}


def agent_middleware(max_tool_calls: int = 5):
    """
    agent_middleware 工厂函数。
    返回包含三个钩子函数的配置对象。
    stream_writer 通过 ContextVar 动态注入，不在初始化阶段绑定。
    """
    return {
        "max_tool_calls": max_tool_calls,
        "awrap_model_call": awrap_model_call,
        "aafter_model": lambda state: aafter_model(state, max_tool_calls=max_tool_calls),
        "awrap_tool_call": awrap_tool_call,
    }
