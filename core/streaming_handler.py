"""
流式输出控制器 - 把 AgentLoop 的队列事件清洗成统一 JSON 数据流推给前端

Packet 类型总表：
  text            — 最终回答文字块（分 chunk 推送，打字机效果）
  think           — 模型思考过程块（前端渲染为折叠思考框，推理结束自动收起）
  tool_call_start — 工具调用开始（前端展示"正在调用 xxx..."）
  tool_call_done  — 工具调用结束（前端展示结果预览）
  custom_status   — 通用状态消息（向后兼容）
  tool_result     — 工具结果预览（向后兼容）
  control         — 流程控制（start / done / error）
"""
import json
import asyncio
from typing import AsyncGenerator, Optional
from dataclasses import dataclass, field

from core.middleware import _stream_writer_var, _thread_id_var


@dataclass
class StreamContext:
    """每次请求独立的流式上下文"""
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    async def write(self, packet: dict):
        await self.queue.put(packet)

    async def read(self) -> Optional[dict]:
        return await self.queue.get()


# ── Packet 构造函数 ────────────────────────────────────────────────

def _make_text_packet(content: str) -> str:
    return "data: " + json.dumps(
        {"type": "text", "content": content},
        ensure_ascii=False
    ) + "\n\n"


def _make_think_packet(content: str) -> str:
    """思考过程块：前端渲染到折叠思考框，字体小、低对比度、打字机动效"""
    return "data: " + json.dumps(
        {"type": "think", "content": content},
        ensure_ascii=False
    ) + "\n\n"


def _make_think_end_packet() -> str:
    """思考结束信号：前端收起思考框，切换到正式回答区"""
    return "data: " + json.dumps(
        {"type": "think_end"},
        ensure_ascii=False
    ) + "\n\n"


def _make_tool_call_start_packet(tool_name: str, tool_args: dict, tool_call_id: str = "") -> str:
    """工具调用开始：前端展示'正在调用 xxx...'+ 呼吸灯"""
    return "data: " + json.dumps(
        {
            "type": "tool_call_start",
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_call_id": tool_call_id,
        },
        ensure_ascii=False
    ) + "\n\n"


def _make_tool_call_done_packet(tool_name: str, result_preview: str, tool_call_id: str = "") -> str:
    """工具调用完成：前端更新状态为已完成 + 结果摘要"""
    return "data: " + json.dumps(
        {
            "type": "tool_call_done",
            "tool_name": tool_name,
            "result_preview": result_preview,
            "tool_call_id": tool_call_id,
        },
        ensure_ascii=False
    ) + "\n\n"


def _make_text_replace_packet(content: str) -> str:
    """
    整体替换已推出的文字：用于内联 tool_call 被识别后，
    将前端消息区中包含 <tool_call> 标签的脏内容替换为干净的纯文字。
    前端收到此 packet 时整体覆盖当前 AI 消息的文本内容。
    """
    return "data: " + json.dumps(
        {"type": "text_replace", "content": content},
        ensure_ascii=False
    ) + "\n\n"


def _make_action_packet(status: str, message: str) -> str:
    return "data: " + json.dumps(
        {"type": "custom_status", "status": status, "message": message},
        ensure_ascii=False
    ) + "\n\n"


def _make_tool_result_packet(tool_name: str, result_preview: str) -> str:
    return "data: " + json.dumps(
        {"type": "tool_result", "tool_name": tool_name, "result_preview": result_preview},
        ensure_ascii=False
    ) + "\n\n"


def _make_control_packet(status: str, **kwargs) -> str:
    payload = {"type": "control", "status": status}
    payload.update(kwargs)
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _make_loop_status_packet(phase: str, status: str, message: str) -> str:
    return "data: " + json.dumps(
        {"type": "loop_status", "phase": phase, "status": status, "message": message},
        ensure_ascii=False,
    ) + "\n\n"


def _make_usage_update_packet(usage: dict) -> str:
    return "data: " + json.dumps(
        {"type": "usage_update", "usage": usage},
        ensure_ascii=False,
    ) + "\n\n"


def _make_observation_packet(tool_use_id: str, tool_name: str, is_error: bool, content_preview: str) -> str:
    return "data: " + json.dumps(
        {
            "type": "observation",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "is_error": is_error,
            "content_preview": content_preview,
        },
        ensure_ascii=False,
    ) + "\n\n"


# ── 核心流式函数 ───────────────────────────────────────────────────

async def stream_chat_response(
    agent_loop,
    user_message,
    thread_id: str,
    user_id: str = "",
    stream_ctx: StreamContext = None,
) -> AsyncGenerator[str, None]:
    """
    核心流式函数 - 外部 API 路由的唯一调用入口。
    启动 AgentLoop.arun() 为后台任务，同时消费 StreamContext 队列推送 SSE。
    """
    if stream_ctx is None:
        stream_ctx = StreamContext()

    yield _make_control_packet("start")

    sent_done = False
    full_response = ""

    try:
        # ContextVar 会在 create_task 时复制到 AgentLoop 任务中。
        # MCP skill 子流程通过 get_stream_writer()/get_thread_id() 读取它们，
        # 因此这里是主 Agent 与 MCP 子工具前台可视化的接线点。
        writer_token = _stream_writer_var.set(stream_ctx.write)
        thread_token = _thread_id_var.set(thread_id)
        try:
            agent_task = asyncio.create_task(
                agent_loop.arun(
                    user_message=user_message,
                    thread_id=thread_id,
                    user_id=user_id,
                    stream_ctx=stream_ctx,
                )
            )

            # 持续从队列读取并推送 SSE
            while True:
                try:
                    packet = await asyncio.wait_for(stream_ctx.queue.get(), timeout=0.1)
                    if packet is None:
                        break

                    ptype = packet.get("type")

                    if ptype == "text":
                        yield _make_text_packet(packet.get("content", ""))

                    elif ptype == "think":
                        yield _make_think_packet(packet.get("content", ""))

                    elif ptype == "think_end":
                        yield _make_think_end_packet()

                    elif ptype == "tool_call_start":
                        yield _make_tool_call_start_packet(
                            packet.get("tool_name", ""),
                            packet.get("tool_args", {}),
                            packet.get("tool_call_id", ""),
                        )

                    elif ptype == "tool_call_done":
                        yield _make_tool_call_done_packet(
                            packet.get("tool_name", ""),
                            packet.get("result_preview", ""),
                            packet.get("tool_call_id", ""),
                        )

                    elif ptype == "text_replace":
                        yield _make_text_replace_packet(packet.get("content", ""))

                    elif ptype == "custom_status":
                        yield _make_action_packet(
                            packet.get("status", "running"),
                            packet.get("message", ""),
                        )

                    elif ptype == "tool_result":
                        yield _make_tool_result_packet(
                            packet.get("tool_name", ""),
                            packet.get("result_preview", ""),
                        )

                    elif ptype == "loop_status":
                        yield _make_loop_status_packet(
                            packet.get("phase", "unknown"),
                            packet.get("status", "running"),
                            packet.get("message", ""),
                        )

                    elif ptype == "usage_update":
                        yield _make_usage_update_packet(packet.get("usage", {}))

                    elif ptype == "observation":
                        yield _make_observation_packet(
                            packet.get("tool_use_id", ""),
                            packet.get("tool_name", ""),
                            bool(packet.get("is_error", False)),
                            packet.get("content_preview", ""),
                        )

                    elif ptype == "control":
                        full_response = packet.get("full_response", "")
                        status = packet.get("status", "done")
                        yield _make_control_packet(status, full_response=full_response)
                        if status in {"done", "error", "abort"}:
                            sent_done = True
                            break

                except asyncio.TimeoutError:
                    if agent_task.done():
                        full_response = agent_task.result()
                        break
                    continue

            # 等待 AgentLoop 任务完全结束
            if not agent_task.done():
                full_response = await agent_task
            else:
                full_response = agent_task.result()
        finally:
            _stream_writer_var.reset(writer_token)
            _thread_id_var.reset(thread_token)

    except asyncio.CancelledError:
        yield _make_control_packet("abort", full_response=full_response)
        sent_done = True
        return
    except Exception as e:
        yield _make_text_packet(f"抱歉，我遇到了一个问题：{str(e)}\n\n请稍后再试。")
        yield _make_control_packet("error", full_response=full_response)
        sent_done = True
        return

    if not sent_done:
        yield _make_control_packet("done", full_response=full_response)
